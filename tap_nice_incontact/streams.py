import csv
import time
from typing import Any, Iterator

import requests
import singer
from singer import Transformer, metrics

from tap_nice_incontact.client import Client


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
    params = {}
    parent = None

    def __init__(self, client: Client):
        self.client = client

    def get_records(self, config: dict = None, is_parent: bool = False) -> list:
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
        parent = self.parent(self.client)
        return parent.get_records(config, is_parent=True)


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
        start_time = singer.get_bookmark(state, self.tap_stream_id, self.replication_key, config['start_date'])
        max_record_value = start_time

        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(config):
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


class SampleStream(FullTableStream):
    """
    Gets records for a sample stream.
    """
    tap_stream_id = 'sample_stream'
    key_properties = ['id']

    def get_records(self, config=None, is_parent=False):
        sample_data = [{
            'string_field': 'some string',
            'datetime_field': '2021-04-23T17:05:41.762537+00:00',
            'integer_field': 3,
            'double_field': 22.78,
        }]

        yield from sample_data


STREAMS = {
    'sample_stream': SampleStream,
}
