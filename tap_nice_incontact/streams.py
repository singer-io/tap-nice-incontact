import csv
import time
import datetime

from datetime import datetime as dt, timedelta, timezone
from typing import Iterator, Tuple

import singer
from singer import Transformer, metrics, utils

from tap_nice_incontact.client import NiceInContactClient, NiceInContactException
from tap_nice_incontact.transform import convert_data_types, transform_iso8601_durations


LOGGER = singer.get_logger()

class BaseStream:
    """
    A base class representing singer streams.

    :param client: The API client used extract records from the external source
    """
    tap_stream_id = None
    replication_method = None
    replication_key = None
    key_properties = []
    valid_replication_keys = []
    path = None
    params = {}
    parent = None
    data_key = None
    convert_data_types = False

    def __init__(self, client: NiceInContactClient):
        self.client = client

    def get_records(self, bookmark_datetime: datetime = None, is_parent: bool = False) -> list:
        """
        Returns a list of records for that stream.

        :param config: The tap config file
        :param is_parent: If true, may change the type of data
            that is returned for a child stream to consume
        :return: list of records
        """
        raise NotImplementedError("Child classes of BaseStream require implementation")

    def set_parameters(self, params: dict) -> None:
        """
        Sets or updates the `params` attribute of a class.

        :param params: Dictionary of parameters to set or update the class with
        """
        self.params = params

    def get_parent_data(self, config: dict = None) -> list:
        """
        Returns a list of records from the parent stream.

        :param config: The tap config file
        :return: A list of records
        """
        # pylint: disable=not-callable
        parent = self.parent(self.client)
        return parent.get_records(config, is_parent=True)

    @staticmethod
    def generate_date_range(start_date: datetime = None,
                            end_date: datetime = utils.now(),
                            period: str = 'days') -> Iterator[list]:
        """Generate 1-period period date-range from the `start_date` and `end_date`"""
        date_list = []

        new_start = start_date

        if period == 'days':
            for day in range(1, (end_date - start_date).days + 1):
                new_end = start_date + timedelta(days=day)
                date_list.append((new_start.isoformat(), new_end.isoformat()))
                new_start = new_end
        elif period == 'hours':
            for hour in range(1, int((end_date - start_date) / timedelta(hours=1)) + 1):
                new_end = (start_date + timedelta(hours=hour))
                date_list.append((new_start.isoformat(), new_end.isoformat()))
                new_start = new_end

        yield from date_list


class IncrementalStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    INCREMENTAL replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'INCREMENTAL'
    batched = False

    def __init__(self, client):
        super().__init__(client)

    def sync(self, state: dict, stream_schema: dict, stream_metadata: dict, config: dict, transformer: Transformer) -> dict:
        """
        The sync logic for an incremental stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        start_time = singer.get_bookmark(state,
                                        self.tap_stream_id,
                                        self.replication_key,
                                        config['start_date'])
        bookmark_datetime = singer.utils.strptime_to_utc(start_time)
        max_record_value = start_time

        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(bookmark_datetime):
                if self.convert_data_types:
                    record = convert_data_types(record, stream_schema)

                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                record_replication_value = singer.utils.strptime_to_utc(transformed_record[self.replication_key])
                if record_replication_value >= singer.utils.strptime_to_utc(max_record_value):
                    singer.write_record(self.tap_stream_id, transformed_record)
                    counter.increment()
                    max_record_value = record_replication_value.isoformat()

        state = singer.write_bookmark(state, self.tap_stream_id, self.replication_key, max_record_value)
        singer.write_state(state)
        return state


class FullTableStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    FULL_TABLE replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'FULL_TABLE'

    def __init__(self, client):
        super().__init__(client)

    def sync(self, state: dict, stream_schema: dict, stream_metadata: dict, config: dict, transformer: Transformer) -> dict:
        """
        The sync logic for an full table stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(config):
                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                singer.write_record(self.tap_stream_id, transformed_record)
                counter.increment()

        singer.write_state(state)
        return state


class ContactsCompleted(IncrementalStream):
    """
    Retrieve completed contacts since `bookmark_datetime`

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/Completed%20Contact%20Details
    """
    tap_stream_id = 'contacts_completed'
    key_properties = ['contactId']
    path = 'contacts/completed'
    replication_key = 'lastUpdateTime' 
    valid_replication_keys = ['lastUpdateTime'] # `lastPollTime` is suggested by the Docs to be used in subsequent requests
    data_key = 'completedContacts'

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator[list]:
        params = {
            "updatedSince": bookmark_datetime.isoformat(),
            "orderBy": self.replication_key + ' asc'
        }

        response = self.client.get(self.path, params=params)

        yield from response.get(self.data_key)


class SkillsSummary(IncrementalStream):
    """
    Retrieve skill summaries for a date-range

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSkillSummaries
    """
    tap_stream_id = 'skills_summary'
    key_properties = ['skillId']
    path = 'skills/summary'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'skillSummaries'
    convert_data_types = True

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class SkillsSLASummary(IncrementalStream):
    """
    Retrieve skill SLA compliance summaries for a date-range.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSLASummaries
    """
    tap_stream_id = 'skills_sla_summary'
    key_properties = ['skillId']
    path = 'skills/sla-summary'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'serviceLevelSummaries'
    convert_data_types = True

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime):
            endpont = self.path
            params = {
                    "startDate": start,
                    "endDate": end
                }
            paging = False
            next_page = True

            while next_page:
                results = self.client.get(endpont, paging=paging, params=params)

                if '_links' in results and results.get('_links', {}).get('next'):
                    paging = True
                    endpont = results.get('_links', {}).get('next')
                    params = None
                else:
                    next_page = False

                LOGGER.info('API call for {} stream returned {:d} records'.format(
                    self.tap_stream_id, results.get('totalRecords'))
                    )

                # add `startDate` and `endDate` to each record
                yield from (dict(rec, **{"startDate": start, "endDate": end}) 
                            for rec in results.get(self.data_key))


class TeamsPerformanceTotal(IncrementalStream):
    """
    Retrieve teams performace summary for a date-range.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/Team%20Performance%20Summary%20Totals%20all
    """
    tap_stream_id = 'teams_performance_total'
    key_properties = ['teamId']
    path = 'teams/performance-total'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'teamPerformanceTotal'
    convert_data_types = True

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime):
            params = {
                "startDate": start,
                "endDate": end
            }
            
            results = self.client.get(self.path, params=params)

            data = transform_iso8601_durations(results.get(self.data_key))

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in data)


class WFMSkillsContacts(IncrementalStream):
    """
    Retrieve WFM statistics for contacts for a date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmskillscontacts
    """
    tap_stream_id = 'wfm_skills_contacts'
    key_properties = ['skillId']
    path = 'wfm-data/skills/contacts'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'contactStats'

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period='hours'):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class WFMSkillsDialerContacts(IncrementalStream):
    """
    Retrieve WFM generated dialer-contact for a date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDailerContactStatistics
    """
    tap_stream_id = 'wfm_skills_dialer_contacts'
    key_properties = ['skillId']
    path = 'wfm-data/skills/dialer-contacts'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'outboundStats'

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period='hours'):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))

class WFMSkillsAgentPerformance(IncrementalStream):
    """
    Retrieve WFM agent performance for a date-range periods of 1 day.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAgentPerformance
    """
    tap_stream_id = 'wfm_skills_agent_performance'
    key_properties = ['skillId', 'agentId']
    path = 'wfm-data/skills/agent-performance'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'skillsPerformance'

    # TODO: confirm what "NOTE: Start and End date cannot span more than 31 days...~" means in API docs.

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period='days'):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class WFMAgents(IncrementalStream):
    """
    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDataAgent
    """
    tap_stream_id = 'wfm_agents'
    key_properties = ['agentId']
    path = 'wfm-data/agents'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'wfoAgentSpecificStats'

    def get_records(self, bookmark_datetime: datetime, is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period='days'):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


STREAMS = {
    'contacts_completed': ContactsCompleted,
    'skills_summary': SkillsSummary,
    'skills_sla_summary': SkillsSLASummary,
    'teams_performance_total': TeamsPerformanceTotal,
    'wfm_skills_contacts': WFMSkillsContacts,
    'wfm_skills_dialer_contacts': WFMSkillsDialerContacts,
    'wfm_skills_agent_performance': WFMSkillsAgentPerformance,
    'wfm_agents': WFMAgents,
}
