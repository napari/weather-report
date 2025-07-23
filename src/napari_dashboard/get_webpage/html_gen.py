import datetime
import logging
import math
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from napari_dashboard.db_update.util import setup_cache
from napari_dashboard.gen_stat.conda import (
    get_conda_download_per_day,
    get_conda_latest_download_info,
    get_conda_total_download_info,
    get_last_month_version_downloads_per_version,
    get_total_conda_download,
)
from napari_dashboard.gen_stat.generate_excel_file import generate_excel_file
from napari_dashboard.gen_stat.github import (
    calc_stars_per_day_cumulative,
    generate_basic_stats,
    generate_contributors_stats,
    get_last_week,
    get_weekly_summary_of_activity,
)
from napari_dashboard.gen_stat.imagesc import get_topics_count
from napari_dashboard.gen_stat.pypi import (
    add_country_info,
    add_plot_info,
    get_active_packages,
    get_download_info,
    get_download_per_operating_system,
    get_download_per_python_version,
    get_per_country_download,
    get_pypi_download_per_day,
    get_recent_releases_date,
    get_total_pypi_download,
    is_country,
)
from napari_dashboard.utils import requests_get

TEMPLATE_DIR = Path(__file__).parent / "webpage_tmpl"
LABELS = [
    "bugfix",
    "feature",
    "documentation",
    "performance",
    "enhancement",
    "maintenance",
]

logger = logging.getLogger(__name__)


def get_plugin_count():
    return len(requests_get("https://api.napari.org/api/plugins").json())


LEGEND_POS = {"x": 0.01, "y": 0.95}


def generate_issue_plot(stats: dict):
    plot = go.Figure()
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["days"],
            y=stats["pr_issue_time_stats"]["issues_open_cumulative"],
            mode="lines",
            name="Issues open",
        )
    )
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["days"],
            y=stats["pr_issue_time_stats"]["issues_closed_cumulative"],
            mode="lines",
            name="Issues close",
        )
    )
    plot.update_layout(legend=LEGEND_POS)

    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_issue_plot2(stats: dict):
    plot = go.Figure()
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"],
            y=stats["pr_issue_time_stats"]["issues_open_weekly"],
            name="Issues open per week",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"],
            y=stats["pr_issue_time_stats"]["issues_closed_weekly"],
            name="Issues close per week",
        )
    )
    plot.update_layout(legend=LEGEND_POS)
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_pull_request_plot(stats: dict):
    plot = go.Figure()
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["days"],
            y=stats["pr_issue_time_stats"]["pr_open_cumulative"],
            mode="lines",
            name="Pull Requests open",
        )
    )
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["days"],
            y=stats["pr_issue_time_stats"]["pr_closed_cumulative"],
            mode="lines",
            name="Pull Requests close",
        )
    )
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["days"],
            y=stats["pr_issue_time_stats"]["pr_merged_cumulative"],
            mode="lines",
            name="Pull Requests merged",
        )
    )
    plot.update_layout(legend=LEGEND_POS)
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_pull_request_plot2(stats: dict):
    plot = go.Figure()
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"],
            y=stats["pr_issue_time_stats"]["pr_open_weekly"],
            name="Pull Requests open per week",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"],
            y=stats["pr_issue_time_stats"]["pr_closed_weekly"],
            name="Pull Requests close per week",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"],
            y=stats["pr_issue_time_stats"]["pr_merged_weekly"],
            name="Pull Requests merged per week",
        )
    )
    plot.update_layout(legend=LEGEND_POS)
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_pull_request_plot3(stats: dict, since: datetime.datetime):
    last_week_count = -(datetime.datetime.now() - since).days // 7
    plot = go.Figure()
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=stats["pr_issue_time_stats"]["pr_merged_feature_weekly"][
                last_week_count:
            ],
            name="Merged features",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=stats["pr_issue_time_stats"]["pr_merged_enhancement_weekly"][
                last_week_count:
            ],
            name="Merged enhancements",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=stats["pr_issue_time_stats"]["pr_merged_bugfix_weekly"][
                last_week_count:
            ],
            name="Merged bugfix",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=stats["pr_issue_time_stats"]["pr_merged_maintenance_weekly"][
                last_week_count:
            ],
            name="Merged maintenance",
        )
    )
    plot.update_layout(
        legend=LEGEND_POS,
        barmode="stack",
        yaxis_title="number of merged pull requests per week",
    )
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def calc_fraction_of_pr(stats, total):
    return [x / t * 100 if t > 0 else 0 for x, t in zip(stats, total)]


def generate_pull_request_plot4(stats: dict, since: datetime.datetime):
    last_week_count = -(datetime.datetime.now() - since).days // 7
    aggregated_data = [
        sum(x)
        for x in zip(
            stats["pr_issue_time_stats"]["pr_merged_feature_weekly"],
            stats["pr_issue_time_stats"]["pr_merged_enhancement_weekly"],
            stats["pr_issue_time_stats"]["pr_merged_bugfix_weekly"],
            stats["pr_issue_time_stats"]["pr_merged_maintenance_weekly"],
        )
    ]
    plot = go.Figure()
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=calc_fraction_of_pr(
                stats["pr_issue_time_stats"]["pr_merged_feature_weekly"],
                aggregated_data,
            )[last_week_count:],
            name="Merged features",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=calc_fraction_of_pr(
                stats["pr_issue_time_stats"]["pr_merged_enhancement_weekly"],
                aggregated_data,
            )[last_week_count:],
            name="Merged enhancements",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=calc_fraction_of_pr(
                stats["pr_issue_time_stats"]["pr_merged_bugfix_weekly"],
                aggregated_data,
            )[last_week_count:],
            name="Merged bugfix",
        )
    )
    plot.add_trace(
        go.Bar(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=calc_fraction_of_pr(
                stats["pr_issue_time_stats"]["pr_merged_maintenance_weekly"],
                aggregated_data,
            )[last_week_count:],
            name="Merged maintenance",
        )
    )
    plot.update_layout(
        barmode="stack",
        yaxis_title="fraction of merged pull requests per week [%]",
    )
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_pull_request_plot5(stats: dict, since: datetime.datetime):
    last_week_count = -(datetime.datetime.now() - since).days // 7
    aggregated_data = [
        sum(x)
        for x in zip(
            stats["pr_issue_time_stats"]["pr_merged_feature_weekly"],
            stats["pr_issue_time_stats"]["pr_merged_enhancement_weekly"],
        )
    ]
    fraction = calc_fraction_of_pr(
        aggregated_data, stats["pr_issue_time_stats"]["pr_merged_weekly"]
    )

    plot = go.Figure()
    plot.add_trace(
        go.Scatter(
            x=stats["pr_issue_time_stats"]["weeks"][last_week_count:],
            y=fraction[last_week_count:],
            mode="lines",
            name="fraction of features and enhancements",
        )
    )
    plot.update_layout(
        yaxis_title="fraction of merged pull requests<br>that are feature/enhancement per week [%]"
    )
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_stars_plot(stars: dict):
    plot = go.Figure()
    plot.add_trace(
        go.Scatter(
            x=stars["day"], y=stars["stars"], mode="lines", name="Stars"
        )
    )
    plot.update_layout(legend=LEGEND_POS)
    return plot.to_html(full_html=False, include_plotlyjs="cdn")


def generate_download_per_day(napari_downloads_per_day):
    df_downloads = pd.DataFrame(
        napari_downloads_per_day.items(), columns=["date", "downloads"]
    )
    return px.line(df_downloads, x="date", y="downloads").to_html(
        full_html=False, include_plotlyjs="cdn"
    )


def generate_version_pie_chart(
    python_version_info: list[tuple[str, int]], filter_value: int = 0
):
    df = pd.DataFrame(python_version_info, columns=["version", "downloads"])
    if filter_value > 0:
        df = df[df["downloads"] > filter_value]
    return px.pie(df, values="downloads", names="version").to_html(
        full_html=False, include_plotlyjs="cdn"
    )


def generate_os_pie_chart(python_version_info):
    df = pd.DataFrame(python_version_info, columns=["os", "downloads"])
    return px.pie(df, values="downloads", names="os").to_html(
        full_html=False, include_plotlyjs="cdn"
    )


def _generate_download_map(data):
    """
    Generate the download map as plotly choropleth
    """
    data = pd.DataFrame(data)
    data = data[data.country_code.map(is_country)]
    data[["iso_alpha", "country_name"]] = data.apply(
        add_country_info, axis=1, result_type="expand"
    )
    data[["log_download", "text"]] = data.apply(
        add_plot_info(data), axis=1, result_type="expand"
    )

    log_download_max = math.ceil(data["log_download"].max())

    return go.Figure(
        data=go.Choropleth(
            locations=data["iso_alpha"],
            z=data["log_download"].astype(float),
            locationmode="ISO-3",
            colorscale="viridis",
            autocolorscale=False,
            text=data["text"],  # hover text
            # marker_line_color='white', # line markers between states
            hovertemplate="%{text}<extra>%{location}</extra>",
            colorbar={
                "title": "downloads",
                "tickvals": list(range(log_download_max)),
                "ticktext": [10**x for x in range(log_download_max)],
                "tickmode": "array",
            },
            showscale=True,
        ),
        layout={"height": 600},
    )


def generate_download_map(data):
    """Generate the download map in high resolution

    Convert the choropleth to a low resolution map in HTML format.
    Such a map is faster to render in the browser, but does not contain
    all the details.
    For example, Singapore is not visible on the map.
    """
    return _generate_download_map(data).to_html(
        full_html=False, include_plotlyjs="cdn"
    )


def generate_download_map_high_res(data):
    """Generate the download map in high resolution

    Convert the choropleth to a high resolution map in HTML format.
    Such a map is slower to render in the browser, but contains
    all the details.
    """
    fig = _generate_download_map(data)
    fig.update_geos(
        resolution=50  # Values can be 110 (low), 50 (medium), or 10 (high) - higher is more detailed
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def get_plugin_info():
    """Get plugin info from napari API"""
    return requests_get("https://api.napari.org/api/plugins").json()


def generate_webpage(
    target_path: Path,
    db_path: Path,
    since_date: datetime.datetime,
    dump_excel: bool = True,
) -> None:
    """
    Generate webpage from template

    Parameters
    ----------
    target_path: Path
        Path where to save the generated webpage
    db_path: Path
        Path to the sqlite database file
    since_date: datetime.datetime
        Since these data up today, part of ths statistics is calculated.
    dump_excel: bool
        If True save the data to excel
    """
    target_path.mkdir(parents=True, exist_ok=True)
    print(f"target path {target_path.absolute()}")
    print(f"db path {db_path.absolute()}, sqlite://{db_path.absolute()}")
    logger.info("Connecting to database %s", db_path.absolute())
    engine = create_engine(f"sqlite:///{db_path.absolute()}")
    setup_cache(timeout=60 * 60 * 4)

    skip_plugins = {"PartSeg", "skan"}
    plugins = get_plugin_info()
    valid_plugins = {x for x in plugins if x not in skip_plugins}

    with Session(engine) as session:
        logger.info("Getting basic statistics from database")
        stats = generate_basic_stats(
            "napari", "napari", session, since_date, LABELS
        )
        logger.info("Calculating stars per day")
        stars = calc_stars_per_day_cumulative("napari", "napari", session)
        stats["stars"] = stars["stars"][-1]
        logger.info("Calculating topics per day")
        stats["contributors"] = generate_contributors_stats(
            [("napari", "napari"), ("napari", "docs"), ("napari", "npe2")],
            session,
            since_date,
        )
        logger.info("forum.imagesc.org topics count")
        forums_stats = get_topics_count(since_date, session)
        logger.info("package download statistics")
        pypi_download_info = get_download_info(
            session, ["napari", "npe2", "napari-plugin-manager"]
        )
        napari_conda_downloads_per_day = get_conda_download_per_day(
            session, "napari"
        )
        napari_conda_last_month_version_downloads = (
            get_last_month_version_downloads_per_version(session, "napari")
        )
        napari_downloads_per_day = get_pypi_download_per_day(session, "napari")
        logger.info("plugin download statistics")
        active_plugin_stats = get_active_packages(
            session, packages=valid_plugins, threshold=1500
        )
        all_plugin_downloads_from_pypi = get_total_pypi_download(
            session, valid_plugins
        )
        all_plugin_downloads_from_conda = get_total_conda_download(
            session, valid_plugins
        )
        under_active_development = get_recent_releases_date(
            session, valid_plugins, since_date
        )
        conda_download_info = {
            "Total": get_conda_total_download_info(
                session, {"napari", "npe2", "napari-plugin-manager"}
            ),
            "Last version": get_conda_latest_download_info(
                session, {"napari", "npe2", "napari-plugin-manager"}
            ),
        }
        python_version_info = get_download_per_python_version(
            session, "napari", since_date
        )
        os_info = get_download_per_operating_system(
            session, "napari", since_date
        )
        last_week_summary = get_weekly_summary_of_activity(session)
        all_downloads = get_per_country_download(session, "napari")
        last_month_downloads = get_per_country_download(
            session,
            "napari",
            datetime.date.today() - datetime.timedelta(days=30),
        )
    logger.info("Data loaded from database")

    # Data to be rendered
    data = {
        "title": "Napari dashboard",
        "project": "Napari",
        "author": "Grzegorz Bokota",
        "stats": stats,
        "today": datetime.datetime.now().strftime("%Y-%m-%d"),
        "base_day": since_date.strftime("%Y-%m-%d"),
        "pypi_downloads": pypi_download_info,
        "forum": forums_stats,
        "conda_downloads": conda_download_info,
        "plugins": {
            "count": get_plugin_count(),
            "all_plugin_downloads_from_pypi": all_plugin_downloads_from_pypi,
            "all_plugin_downloads_from_conda": all_plugin_downloads_from_conda,
            "active": len(active_plugin_stats),
            "under_active_development": under_active_development,
            "skip": skip_plugins,
        },
        "py_version": generate_version_pie_chart(python_version_info, 100),
        "os_plot": generate_os_pie_chart(os_info),
        "napari_downloads_per_day": generate_download_per_day(
            napari_downloads_per_day
        ),
        "napari_conda_downloads_per_day": generate_download_per_day(
            napari_conda_downloads_per_day
        ),
        "napari_conda_version_last_month": generate_version_pie_chart(
            napari_conda_last_month_version_downloads, 100
        ),
        "issue_activity": generate_issue_plot(stats),
        "issue_activity2": generate_issue_plot2(stats),
        "pr_activity_plot": generate_pull_request_plot(stats),
        "pr_activity_plot2": generate_pull_request_plot2(stats),
        "pr_activity_plot3": generate_pull_request_plot3(stats, since_date),
        "pr_activity_plot4": generate_pull_request_plot4(stats, since_date),
        "pr_activity_plot5": generate_pull_request_plot5(stats, since_date),
        "stars_plot": generate_stars_plot(stars),
        "download_map": generate_download_map(all_downloads),
        "download_map_high_res": generate_download_map_high_res(all_downloads),
        "download_map_last_month": generate_download_map(last_month_downloads),
        "download_map_last_month_high_res": generate_download_map_high_res(
            last_month_downloads
        ),
        "last_week_summary": last_week_summary,
        "last_week_range": get_last_week(),
    }
    print("generating webpage")

    # Create an environment
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

    # Load the template
    index_template = env.get_template("index.html")
    dashboard_css_template = env.get_template("dashboard.css")
    color_mode_template = env.get_template("color-modes.js")

    # Render the template with data
    with open(target_path / "index.html", "w") as f:
        f.write(index_template.render(data))

    with open(target_path / "dashboard.css", "w") as f:
        f.write(dashboard_css_template.render(data))

    with open(target_path / "color-modes.js", "w") as f:
        f.write(color_mode_template.render(data))

    if dump_excel:
        print("Save data to excel")

        with Session(engine) as session:
            generate_excel_file(target_path / "napari_dashboard.xlsx", session)
