import singer
from singer import Transformer, metadata

from tap_nice_incontact.client import NiceInContactClient
from tap_nice_incontact.streams import STREAMS

LOGGER = singer.get_logger()

def sync(config, state, catalog):
    """ Sync data from tap source """

    client_params = {
        'api_key': config.get('api_key'),
        'api_secret': config.get('api_secret'),
        'api_cluster': config.get('api_cluster'),
        'api_version': config.get('api_version'),
        'auth_domain': config.get('auth_domain'),
        'user_agent': config.get('user_agent'),
        'start_date': config.get('start_date')
    }

    client = NiceInContactClient(**client_params)

    with Transformer() as transformer:
        for stream in catalog.get_selected_streams(state):
            tap_stream_id = stream.tap_stream_id
            stream_obj = STREAMS[tap_stream_id](client)
            stream_schema = stream.schema.to_dict()
            stream_metadata = metadata.to_map(stream.metadata)

            LOGGER.info('Starting sync for stream: %s', tap_stream_id)

            state = singer.set_currently_syncing(state, tap_stream_id)
            singer.write_state(state)

            singer.write_schema(
                tap_stream_id,
                stream_schema,
                stream_obj.key_properties,
                stream.replication_key
            )

            state = stream_obj.sync(state, stream_schema, stream_metadata, config, transformer)
            singer.write_state(state)

    state = singer.set_currently_syncing(state, None)
    singer.write_state(state)
