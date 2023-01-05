import time
import datetime
import requests
import csv
import json

from datetime import timedelta
from typing import Iterator

import singer
from singer import Transformer, metrics, utils

from tap_nice_incontact.client import NiceInContactClient, NiceInContact403Exception, NiceInContact5xxException
from tap_nice_incontact.transform import convert_data_types, transform_iso8601_durations, convert_data_keys


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
    default_period = 'days'

    def __init__(self, client: NiceInContactClient):
        self.client = client

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> list:
        """
        Returns a list of records for that stream.

        :param config: The tap config file
        :param bookmark_datetime: The stream bookmark datetime
            object for INCREMENTAL replication
        :param is_parent: If true, may change the type of data
            that is returned for a child stream to consume
        :return: list of records
        """
        raise NotImplementedError("Child classes of BaseStream require implementation")

    def get_parent_data(self, config: dict = None) -> list:
        """
        Returns a list of records from the parent stream.

        :param config: The tap config file
        :return: A list of records
        """
        if not self.parent:
            raise NotImplementedError("Child classes of BaseStream need to set the parent class")
        # pylint: disable=not-callable
        parent = self.parent(self.client)
        return parent.get_records(config, is_parent=True)

    @staticmethod
    def generate_date_range(start_date: datetime = None,
                            end_date: datetime = utils.now(),
                            period: str = 'days') -> Iterator[list]:
        """
        Generates 1-day, 1-hour, or 5-minute periods date-range
            from `start_date` to `end_date`

        :param start_date: The starting datetime to use
        :param end_date: The ending datetime to use, defaults to now
        :param period: The date-range period between dates,
            defaults to 'days'
        """
        date_list = []

        new_start = start_date

        if period == 'days':
            for day in range(1, (end_date - start_date).days + 1):
                new_end = start_date + timedelta(days=day)
                date_list.append((utils.strftime(new_start), utils.strftime(new_end)))
                new_start = new_end
        elif period == 'hours':
            for hour in range(1, int((end_date - start_date) / timedelta(hours=1)) + 1):
                new_end = (start_date + timedelta(hours=hour))
                date_list.append((utils.strftime(new_start), utils.strftime(new_end)))
                new_start = new_end
        elif period == 'minutes':
            for minutes in range(5, int((end_date - start_date) / timedelta(minutes=1)) + 5, 5):
                new_end = start_date + timedelta(minutes=minutes)
                date_list.append((utils.strftime(new_start), utils.strftime(new_end)))
                new_start = new_end

        yield from date_list

    @staticmethod
    def check_start_date(bookmark_datetime: datetime = None, days: int = 31) -> datetime:
        """Check in the bookmark_datetime is more than n days in the past"""

        n_days = utils.now() - timedelta(days=days)

        if bookmark_datetime < n_days:
            return n_days

        return bookmark_datetime


# pylint: disable=abstract-method
class IncrementalStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    INCREMENTAL replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'INCREMENTAL'
    batched = False

    def sync(self,
            state: dict,
            stream_schema: dict,
            stream_metadata: dict,
            config: dict,
            transformer: Transformer) -> dict:
        """
        The sync logic for an incremental stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        start_date = singer.get_bookmark(state,
                                        self.tap_stream_id,
                                        self.replication_key,
                                        config['start_date'])
        bookmark_datetime = singer.utils.strptime_to_utc(start_date)
        max_datetime = bookmark_datetime

        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(config, bookmark_datetime):
                if self.convert_data_types:
                    record = convert_data_types(record, stream_schema)

                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                # pylint: disable=line-too-long
                record_datetime = singer.utils.strptime_to_utc(transformed_record[self.replication_key])
                if record_datetime >= bookmark_datetime:
                    singer.write_record(self.tap_stream_id, transformed_record)
                    counter.increment()
                    max_datetime = max(record_datetime, bookmark_datetime)

            bookmark_date = singer.utils.strftime(max_datetime)

        state = singer.write_bookmark(state,
                                    self.tap_stream_id,
                                    self.replication_key,
                                    bookmark_date)
        singer.write_state(state)
        return state


class FullTableStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    FULL_TABLE replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'FULL_TABLE'

    def sync(self,
            state: dict,
            stream_schema: dict,
            stream_metadata: dict,
            config: dict,
            transformer: Transformer) -> dict:
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


class Agents(FullTableStream):
    """
    Retrieve agents updated since the bookmark time

    Docs: https://developer.niceincontact.com/API/AdminAPI#/Agents/get-agents
    """
    tap_stream_id = 'agents'
    key_properties = ['agentId']
    path = 'agents'
    data_key = 'agents'

    def get_records(self,
                    config: dict = None,
                    is_parent: bool = False) -> Iterator[list]:
        # bookmark_datetime = self.check_start_date(bookmark_datetime, 30)
        has_more_records = True
        skip = 0

        # API is limited to 10K records per response, use skip param to get all records
        while has_more_records:
            params = {
                "skip": skip
            }

            response = self.client.get(self.path, params=params)

            if not response:
                has_more_records = False
            else:
                skip += len(response.get(self.data_key))

                yield from response.get(self.data_key)


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

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator[list]:
        bookmark_datetime = self.check_start_date(bookmark_datetime, 30)
        records = True
        skip = 0

        # API is limited to 10K records per response, use skip param to get all records
        while records:
            params = {
                "updatedSince": bookmark_datetime.isoformat(),
                "orderBy": self.replication_key + ' asc',
                "skip": skip
            }

            response = self.client.get(self.path, params=params)

            if not response:
                records = False
            else:
                skip += len(response.get(self.data_key))

                yield from response.get(self.data_key)


class SkillsSummary(IncrementalStream):
    """
    Retrieve skill summaries for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSkillSummaries
    """
    tap_stream_id = 'skills_summary'
    key_properties = ['skillId', 'startDate', 'endDate']
    path = 'skills/summary'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'skillSummaries'
    convert_data_types = True
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class SkillsSLASummary(IncrementalStream):
    """
    Retrieve skill SLA compliance summaries for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSLASummaries
    """
    tap_stream_id = 'skills_sla_summary'
    key_properties = ['skillId', 'startDate', 'endDate']
    path = 'skills/sla-summary'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'serviceLevelSummaries'
    convert_data_types = True
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            endpoint = self.path
            params = {
                    "startDate": start,
                    "endDate": end
                }
            paging = False
            next_page = True

            while next_page:
                results = self.client.get(endpoint, paging=paging, params=params)

                if '_links' in results and results.get('_links', {}).get('next'):
                    paging = True
                    endpoint = results.get('_links', {}).get('next')
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
    Retrieve teams performace summary for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/Reporting/Team%20Performance%20Summary%20Totals%20all
    """
    tap_stream_id = 'teams_performance_total'
    key_properties = ['teamId', 'startDate', 'endDate']
    path = 'teams/performance-total'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'teamPerformanceTotal'
    convert_data_types = True
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
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
    Retrieve WFM statistics for contacts for date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmskillscontacts
    """
    tap_stream_id = 'wfm_skills_contacts'
    key_properties = ['skillId', 'intervalStartDate']
    path = 'wfm-data/skills/contacts'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'contactStats'
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period=self.default_period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class WFMSkillsDialerContacts(IncrementalStream):
    """
    Retrieve WFM generated dialer-contact for date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDailerContactStatistics
    """
    tap_stream_id = 'wfm_skills_dialer_contacts'
    key_properties = ['skillId', 'intervalStartDate']
    path = 'wfm-data/skills/dialer-contacts'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'outboundStats'
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period=self.default_period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))

class WFMSkillsAgentPerformance(IncrementalStream):
    """
    Retrieve WFM agent performance for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAgentPerformance
    """
    tap_stream_id = 'wfm_skills_agent_performance'
    key_properties = ['skillId', 'agentId', 'halfHour']
    path = 'wfm-data/skills/agent-performance'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'skillsPerformance'
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class WFMAgents(IncrementalStream):
    """
    Retrieve WFM agent metadata changes for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDataAgent
    """
    tap_stream_id = 'wfm_agents'
    key_properties = ['agentId', 'modDateTime']
    path = 'wfm-data/agents'
    replication_key = 'endDate'
    valid_replication_keys = ['startDate', 'endDate']
    data_key = 'wfoAgentSpecificStats'
    default_period = 'hours'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # add `startDate` and `endDate` to each record
            yield from (dict(rec, **params) for rec in results.get(self.data_key))


class WFMAgentsScheduleAdherence(IncrementalStream):
    """
    Retrieve WFM schedule adherence statistics for date-range periods of 5 minutes.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAdherenceStatistics
    """
    tap_stream_id = 'wfm_agents_schedule_adherence'
    key_properties = ['agentId', 'agentStateId', 'startDate']
    path = 'wfm-data/agents/schedule-adherence'
    replication_key = 'callEndDate'
    valid_replication_keys = ['startDate', 'callEndDate']
    data_key = 'agentStateHistory'
    default_period = 'minutes'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        for start, end in self.generate_date_range(bookmark_datetime, period=self.default_period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # skip over date-range periods that don't return data (204)
            if not results:
                continue

            # add `callStartDate` and `callEndDate` to each record
            yield from (dict(rec, **{"callStartDate": start, "callEndDate": end})
                        for rec in results.get(self.data_key) if rec)


class WFMAgentsScorecards(IncrementalStream):
    """
    Retrieve WFM agent scorecards statistics for a default date-range periods of 1 hour.

    Docs: https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAgentScorecard
    """
    tap_stream_id = 'wfm_agents_scorecards'
    key_properties = ['agentId', 'startDate']
    path = 'wfm-data/agents/scorecards'
    replication_key = 'callEndDate'
    valid_replication_keys = ['startDate', 'callEndDate']
    data_key = 'wfmScorecardStats'
    default_period = 'hour'

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            params = {
                "startDate": start,
                "endDate": end
            }

            results = self.client.get(self.path, params=params)

            # skip over date-range periods that don't return data (204)
            if not results:
                continue

            # add `callStartDate` and `callEndDate` to each record
            yield from (dict(rec, **{"callStartDate": start, "callEndDate": end})
                        for rec in results.get(self.data_key))


class DataExtractionStream(IncrementalStream):
    """
    Base class for streams pulling data via the Data Extraction API endpoints
    Docs: https://help.nice-incontact.com/content/recording/dataextractionapi.htm
    :param client: The API client used extract records from the external source
    """
    replication_method = 'INCREMENTAL'
    entity_name = ''
    entity_version = 3

    # amount of time to delay before polling again
    poll_delay = 5
    # number of seconds before timing out
    poll_timeout = 300
    default_period = 'days'

    path = 'jobs'

    def get_status_uri(self, job_id):
        return f'{self.path}/{job_id}'

    def download_csv(self, csv_uri):
        rows = []
        with requests.get(csv_uri, stream=True) as r:
            lines = (line.decode('utf-8') for line in r.iter_lines())
            for row in csv.DictReader(lines):
                rows.append(row)
        return rows

    def create_job(self, start_date, end_date):
        """ Create a new job in the data extraction API """
        data = {
            "entityName": self.entity_name,
            "startDate": start_date.strftime('%Y-%m-%d'),
            "endDate": end_date.strftime('%Y-%m-%d'),
            "version": str(self.entity_version),
        }
        job_id = self.client.post(
            self.path,
            data=json.dumps(data),
            headers={'Content-Type': 'application/json'},
            is_data_extraction=True
        )
        return job_id

    def get_job_details(self, job_id):
        job_path = f'{self.path}/{job_id}'
        results = self.client.get(job_path, is_data_extraction=True)
        if 'jobStatus' not in results:
            return None
        return results['jobStatus']

    def fetch_data_export(self, start_date, end_date, config: dict = None):

        poll_delay = self.poll_delay
        poll_timeout = self.poll_timeout
        if config.get('poll_settings'):
            poll_delay = config.get('poll_settings', {}).get('delay')
            poll_timeout = config.get('poll_settings', {}).get('timeout')

        job_id = self.create_job(start_date, end_date)
        
        LOGGER.info(f'Created job: {job_id}')

        job_details = None
        ready = False
        poll_attempt = 0

        start_time = datetime.datetime.utcnow()

        while not ready:
            if (datetime.datetime.utcnow() - start_time).total_seconds() > poll_timeout:
                raise Exception("data extraction job status timeout")

            job_details = self.get_job_details(job_id)
            if job_details is None:
                raise Exception("data extraction job failure", job_id)

            status = job_details['status']
            LOGGER.info(f'Job status ({job_id}): {status}')

            if status == 'SUCCEEDED':
                ready = True
            elif status == 'RUNNING':
                time.sleep(poll_delay)
            else:
                # Job status can also be: Failed, Cancelled, and Expired.
                # https://help.nice-incontact.com/content/recording/dataextractionapi.htm
                raise ValueError("Data extraction job failure", job_details)

        records = self.download_csv(job_details['result']['url'])
        return records

    def sync(self,
             state: dict,
             stream_schema: dict,
             stream_metadata: dict,
             config: dict,
             transformer: Transformer) -> dict:
        """
        The sync logic for an incremental stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        

        start_date = singer.get_bookmark(state,
                                        self.tap_stream_id,
                                        self.replication_key,
                                        config['start_date'])
        bookmark_datetime = singer.utils.strptime_to_utc(start_date)
        max_datetime = bookmark_datetime        
        
        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(config, bookmark_datetime):
                # Convert data keys for CSV outputs to the correct field format
                record = convert_data_keys(record)

                if self.convert_data_types:
                    record = convert_data_types(record, stream_schema)

                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                # pylint: disable=line-too-long
                record_datetime = singer.utils.strptime_to_utc(transformed_record[self.replication_key])
                if record_datetime >= bookmark_datetime:
                    singer.write_record(self.tap_stream_id, transformed_record)
                    counter.increment()
                    max_datetime = max(record_datetime, bookmark_datetime)

            bookmark_date = singer.utils.strftime(max_datetime)

        state = singer.write_bookmark(state,
                                    self.tap_stream_id,
                                    self.replication_key,
                                    bookmark_date)
        singer.write_state(state)
        return state

    def get_records(self,
                    config: dict = None,
                    bookmark_datetime: datetime = None,
                    is_parent: bool = False) -> Iterator:
        if config.get('periods'):
            period = config.get('periods', {}).get(self.tap_stream_id)
        else:
            period = self.default_period

        for start, end in self.generate_date_range(bookmark_datetime, period=period):
            start_date = singer.utils.strptime_to_utc(start)
            end_date = singer.utils.strptime_to_utc(end)

            try:
                results = self.fetch_data_export(start_date, end_date, config)
            except (NiceInContact403Exception, NiceInContact5xxException, ValueError) as e:
                # We get a 403 exception if we are rate-limited by the data
                # extraction API. Exclude these errors and wait until the
                # next tap run to continue from the start datetime.
                #
                # Otherwise break if we receive a server error or invalid job status.
                break

            if not results:
                # skip over date-range periods that don't return data (204)
                continue
            else:
                yield from (dict(rec, **{"Job Start Date": start, "Job End Date": end})
                            for rec in results)


class QMWorkflows(DataExtractionStream):
    """
    Retrieve QM Workflow via the data extraction api.

    Docs: https://help.nice-incontact.com/content/recording/dataextractionapi.htm#QMWorkflowEntityandCSVFile
    """
    tap_stream_id = 'qm_workflows'

    # Entity information required to create a job
    entity_name = 'qm-workflows'
    entity_version = 3
    
    key_properties = ['lastUpdated', 'startDate', 'workflowId']
    replication_key = 'jobEndDate'
    valid_replication_keys = ['jobEndDate', 'lastUpdated', 'startDate']
    data_key = 'qmWorkflows'
    convert_data_types = True
    default_period = 'days'


STREAMS = {
    'agents': Agents,
    'contacts_completed': ContactsCompleted,
    'skills_summary': SkillsSummary,
    'skills_sla_summary': SkillsSLASummary,
    'teams_performance_total': TeamsPerformanceTotal,
    'wfm_skills_contacts': WFMSkillsContacts,
    'wfm_skills_dialer_contacts': WFMSkillsDialerContacts,
    'wfm_skills_agent_performance': WFMSkillsAgentPerformance,
    'wfm_agents': WFMAgents,
    'wfm_agents_schedule_adherence': WFMAgentsScheduleAdherence,
    'wfm_agents_scorecards': WFMAgentsScorecards,
    'qm_workflows': QMWorkflows
}
