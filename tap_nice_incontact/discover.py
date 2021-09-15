import json
import os

from singer import metadata
from singer.catalog import Catalog

from tap_nice_incontact.streams import STREAMS


def get_abs_path(path):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

def _get_key_properties_from_meta(schema_meta):
    return schema_meta[0].get('metadata').get('table-key-properties')

def _get_replication_method_from_meta(schema_meta):
    return schema_meta[0].get('metadata').get('forced-replication-method')

def _get_replication_key_from_meta(schema_meta):
    if _get_replication_method_from_meta(schema_meta) == 'INCREMENTAL':
        return schema_meta[0].get('metadata').get('valid-replication-keys')[0]
    return None

def get_schemas():
    """
    Builds the singer schema and metadata dictionaries.
    """
    schemas = {}
    schemas_metadata = {}

    for stream_name, stream_object in STREAMS.items():

        schema_path = get_abs_path('schemas/{}.json'.format(stream_name))
        with open(schema_path) as file:
            schema = json.load(file)

        if stream_object.replication_method == 'INCREMENTAL':
            replication_keys = stream_object.valid_replication_keys
        else:
            replication_keys = None

        meta = metadata.get_standard_metadata(
            schema=schema,
            key_properties=stream_object.key_properties,
            replication_method=stream_object.replication_method,
            valid_replication_keys=replication_keys,
        )

        meta = metadata.to_map(meta)

        if replication_keys:
            for replication_key in replication_keys:
                meta = metadata.write(meta, ('properties', replication_key), 'inclusion', 'automatic')

        meta = metadata.to_list(meta)

        schemas[stream_name] = schema
        schemas_metadata[stream_name] = meta

    return schemas, schemas_metadata


def discover():

    schemas, schemas_metadata = get_schemas()
    streams = []

    for schema_name, schema in schemas.items():
        schema_meta = schemas_metadata[schema_name]

        catalog_entry = {
            'stream': schema_name,
            'tap_stream_id': schema_name,
            'schema': schema,
            'key_properties': _get_key_properties_from_meta(schema_meta),
            'replication_method': _get_replication_method_from_meta(schema_meta),
            'replication_key': _get_replication_key_from_meta(schema_meta),
            'metadata': schema_meta
        }

        streams.append(catalog_entry)

    return Catalog.from_dict({'streams': streams})
