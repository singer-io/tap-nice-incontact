import json
from isodate import parse_duration
from isodate.isoerror import ISO8601Error

from singer.transform import SchemaMismatch


def convert_data_types(data: dict, schema: dict) -> dict:
    """
    Function to convert NICE inContact API returned data to the correct
        schema date type. Some endpoints return all fields as strings.

    :param data: A dictionary containing a single record from API response.
    :param schema: A dictionary with the Singer schema for the relevant stream.
    :return: A dictionary with the data converted to the correct data type
        based on the streams schema.
    """
    converted_data = {}
    error_message = []

    for field, value in data.items():
        field_prop = schema.get('properties', {}).get(field)

        if field not in schema.get('properties').keys():
            error_message.append(f'{field}: does not match: {field_prop.get("type")}')
            raise SchemaMismatch([error_message, schema])

        if 'integer' in field_prop.get('type') and not isinstance(value, int):
            value = int(value)

        if field_prop.get('format') == 'singer.decimal' and not isinstance(value, str):
            value = str(value)

        if 'boolean' in field_prop.get('type') and not isinstance(value, bool):
            value = bool(json.loads(value.lower()))

        converted_data.update({field: value})

    return converted_data

def transform_iso8601_durations(data: list) -> list:
    """
    Function to transform ISO8601 Durantions to seconds.

    :param data: A list with records to transform.
    """
    transformed_data = []

    for record in data:
        new_record = {}
        for field, value in record.items():
            try:
                parsed_duration = parse_duration(value).total_seconds()
                value = int(parsed_duration)
            except ISO8601Error:
                pass

            new_record.update({field: value})
        transformed_data.append(new_record)

    return transformed_data
