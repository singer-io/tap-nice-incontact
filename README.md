# tap-nice-incontact

This is a [Singer](https://singer.io) tap that produces JSON-formatted data
following the [Singer
spec](https://github.com/singer-io/getting-started/blob/master/docs/SPEC.md).

This tap:

- Pulls raw data from [NICE inContact Reporting API](https://developer.niceincontact.com/API/ReportingAPI)
- Extracts the following resources:
    - [Contacts - Completed](https://developer.niceincontact.com/API/ReportingAPI#/Reporting/Completed%20Contact%20Details)
    - [Skills - Summary](https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSkillSummaries)
    - [Skills - SLA Summary](https://developer.niceincontact.com/API/ReportingAPI#/Reporting/getFullSLASummaries)
    - [Teams - Performance Total](https://developer.niceincontact.com/API/ReportingAPI#/Reporting/Team%20Performance%20Summary%20Totals%20all)
    - [WFM - Skills - Contacts](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmskillscontacts)
    - [WFM - Skills - Dialer Contacts](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDailerContactStatistics)
    - [WFM - Skills - Agent Performance](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAgentPerformance)
    - [WFM - Agents](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmDataAgent)
    - [WFM - Agents - Schedule Adherence](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAdherenceStatistics)
    - [WFM - Agents - Scorecards](https://developer.niceincontact.com/API/ReportingAPI#/WFM%20Data/wfmAgentScorecard)
- Outputs the schema for each resource
- Incrementally pulls data based on the input state

## Bookmarking Strategy
Most of the streams produce data for a "reporting period" which defaults to 1 hour. Some streams require a reporting period of 5 minutes. Each incremental stream class in `streams.py` has a `replication_key` that the tap uses to bookmark on.


## Authentication
The tap is built around the NICE inContact UserHub authentication process. This [guide](https://developer.niceincontact.com/Documentation/UserHubGettingStarted) will show the steps required to get an `api_key` and `api_secret`.


## Config

The tap accepts the following config items:

| field | type | required | description |
| :---- | :--: | :------: | :---------- |
| `start_date` | string | yes | RFC3339 date string "2017-01-01T00:00:00Z" |
| `api_key` | string | yes | NICE inContact API key (see [Authentication](#Authentication)) |
| `api_secret` | string | yes | NICE inContact API secret (see [Authentication](#Authentication)) |
| `api_cluster` | string | yes | NICE inContact instance cluster. Example: `"c42"` |
| `api_version` | string | no | NICE inContact API version. Default is  `"21.0"` |
| `user_agent` | string | yes | Process and email for API logging purposes. Example: `tap-nice-incontact <api_user_email@your_company.com>` |
| `auth_domain` | string | no | The NICE inContact auth domain/region to use. Default is `"na1"`. See [Authentication](#Authentication) for more. |
| `periods` | object | no | stream specific reporting periods (see [below](#Reporting%20Periods)) |


Example config:

```json
{
  "start_date": "2017-01-01T00:00:00Z",
  "api_key": "<NICE inContact API key>",
  "api_secret": "<NICE inContact API secret>",
  "api_cluster": "<NICE inContact instance cluster>",
  "api_version": "<NICE inContact API version>",
  "user_agent": "tap-nice-incontact <<api_user_email@your_company.com>>",
  "periods": {
    "skills_summary": "days",
    "skills_sla_summary": "days",
    "teams_performance_total": "days",
    "wfm_skills_agent_performance": "days",
    "wfm_agents": "days",
    "wfm_agents_scorecards": "days"
  }
}
```


## Reporting Periods
For `periods` the structure is as follows:

| stream | reporting period |
| :----: | :--------------- | 
| `stream_name` | the tap supports 1 `days`, 1 `hours`, and 5 `minutes` |


## Quick Start
1. Install

Clone this repository, and then install using setup.py. We recommend using a virtualenv:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
$ pip install -e .
```

2. Create your tap's config.json file. Look at this [table](#Config) for format and required fields.

3. Run the Tap in Discovery Mode This creates a catalog.json for selecting objects/fields to integrate:

```bash
tap-nice-incontact --config config.json --discover > catalog.json
```

See the Singer docs on discovery mode [here](https://github.com/singer-io/getting-started/blob/master/docs/DISCOVERY_MODE.md#discovery-mode).

4. Run the Tap in Sync Mode (with catalog) and write out to state file

For Sync mode:

```bash
$ tap-nice-incontact --config tap_config.json --catalog catalog.json >> state.json
$ tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
```

To load to json files to verify outputs:

```bash
$ tap-nice-incontact --config tap_config.json --catalog catalog.json | target-json >> state.json
$ tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
```

To pseudo-load to Stitch Import API with dry run:

```bash
$ tap-nice-incontact --config tap_config.json --catalog catalog.json | target-stitch --config target_config.json --dry-run >> state.json
$ tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
```


---

Copyright &copy; 2018 Stitch
