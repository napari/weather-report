# Napari Dashboard

Implementation of dashboard with statistics about napari project development and usage.


## Overview 

This code is using Google Drive as data storage between different sessions. 

There are three workflows triggered by GitHub Actions:

1. `weekly_zulip_report.yml` - this workflow is triggered every Monday at 12:00 UTC and on every push to the `main` branch. 
  It fetches the data from Google Drive and uses it to prepare the weekly report about opened, updated, and closed issues and pull requests in the last week.
  If it is triggered by push, the output is sent to `metrics and analytics` stream, otherwise it is sent to `core-dev` stream.

2. `refresh_webpage.yml` - this workflow also fetches the latest data from Google Drive, consisting of the recent data from:
    * Google Big Query (napari downloads from pypi)
    * GitHub API (Stars, Pull Requests, Issues for napari, docs and npe2)
    * forum.image.sc (number of topics and posts)
    * Conda (number of downloads)
    * pepy.tech (basic statistics about plugin downloads)
    * pypistats.org (basic statistics about plugin downloads)
    * pypi.org API (release of npari and plugins)

    The data are saved to database and webpage is updated with the latest data.
    Then data are saved to Google Drive for future use.

3. `meeting_reminder.yml` - announces upcoming meetings from the
   [napari public calendar](https://napari.org/stable/community/meeting_schedule.html)
   in the `community-meeting` Zulip stream. Events are read from the public iCal feed, so no Google API key is needed.
    * Friday 12:00 UTC - meetings on Saturday, Sunday and Monday (so Monday meetings are announced before the weekend),
    * Monday 08:00 UTC - meetings from Tuesday to Friday.

   Every meeting is posted in its own topic, named like `2026-11-12/13 napari community meeting (Pacific)`.
   The topic lists every date on which the meeting is during waking hours in America, Europe or Australia.
   Cancelled meetings, all-day entries and meetings with `core team` or `steering council` in the title are skipped.
   On every push to the `main` branch (and on manual run) meetings of the whole next week are sent to the single
   `Meeting reminder` topic of the `metrics and analytics` stream to check that the bot works.

   To preview the messages locally run `uv run python -m napari_dashboard.meeting_reminder --window next-week`
   (`--window friday|monday|next-week`, `--today YYYY-MM-DD` to pretend another date).

## Configuration overview

To properly run the workflows you need to set up the following secrets in the repository:

* `SERVICE_SECRETS` - JSON file with Google Service Account credentials. The service account should have access to Google Drive and Google Big Query.
* `ZULIP_API_KEY` - API key for Zulip bot. Key required to send messages to Zulip.
* `PEPY_KEY` - API key for pepy.tech. Key required to fetch data about plugin downloads.
