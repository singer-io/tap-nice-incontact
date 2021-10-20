import json
import singer
from singer import utils

from tap_nice_incontact.discover import discover
from tap_nice_incontact.sync import sync

REQUIRED_CONFIG_KEYS = [
    "start_date",
    "api_key",
    "api_secret",
    "api_cluster",
    "user_agent"
    ]

LOGGER = singer.get_logger()


@utils.handle_top_exception(LOGGER)
def main():
    # Parse command line arguments
    args = utils.parse_args(REQUIRED_CONFIG_KEYS)

    config = args.config

    # parse "periods" from config
    periods = config.get("periods", {})
    if periods and isinstance(periods, str):
        periods = json.loads(periods)
        config.update({"periods": periods})

    # If discover flag was passed, run discovery mode and dump output to stdout
    if args.discover:
        catalog = discover()
        catalog.dump()
    # Otherwise run in sync mode
    else:
        if args.catalog:
            catalog = args.catalog
        else:
            catalog = discover()
        sync(config, args.state, catalog)


if __name__ == "__main__":
    main()
