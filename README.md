# Napari Dashboard

Implementation of dashboard with statistics about napari project development and usage.


## Overview 

This code is using Google Drive as data storage between different sessions. 

There are two workflows triggered by GitHub Actions:

1. `weekly_zulip_report.yml` - this workflow is triggered every Monday at 12:00 UTC. And on every push to the `main` branch. 
  It fetches the data from Google Drive and based on it, it prepares weekly report about opened, updated and closed issues and pull requests in the last week.
  If it is triggered by push, the output is sent to `metrics and analytics` stream, otherwise it is sent to `core-dev` stream.

2. `refresh_webpage.yml` - this workflow fetch the latest data from Google Drive fetch most recent data from:
    * Google Big Query (napari downloads from pypi)
    * GitHub API (Stars, Pull Requests, Issues for napari, docs and npe2)
    * forum.image.sc (number of topics and posts)
    * Conda (number of downloads)
    * pepy.tech (basic statistics about plugin downloads)
    * pypistats.org (basic statistics about plugin downloads)
    * pypi.org API (release of npari and plugins)

    The data are saved to database and webpage is updated with the latest data.
    Then data are saved to Google Drive for future use.

## Configuration overview

To properly run the workflows you need to set up the following secrets in the repository:

* `SERVICE_SECRETS` - JSON file with Google Service Account credentials. The service account should have access to Google Drive and Google Big Query.
* `ZULIP_API_KEY` - API key for Zulip bot. Key required to send messages to Zulip.
* `PEPY_KEY` - API key for pepy.tech. Key required to fetch data about plugin downloads.
