import datetime
import logging
import math
import os
import time

import requests
from github import (
    Auth,
    Github,
    PullRequest as GHPullRequest,
    Repository as GHRepository,
)
from sqlalchemy.orm import Session
from tqdm import tqdm

from napari_dashboard.db_schema.github import (
    BOT_SET,
    ArtifactDownloads,
    GithubUser,
    IssueComment,
    Issues,
    Labels,
    PullRequestComments,
    PullRequestCommits,
    PullRequestReviews,
    PullRequests,
    Release,
    Repository,
    Stars,
)
from napari_dashboard.db_update.util import get_or_create
from napari_dashboard.gen_stat.github import get_repo_model

GH_TOKEN_ = os.environ.get("GH_TOKEN_")
logger = logging.getLogger(__name__)

_G = None

PR_COMMITS_HEADER = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ.get('GH_TOKEN_')}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_commits(pr: GHPullRequest):
    commits_json = []
    i = 1
    while i < math.ceil(pr.commits / 100) + 1:
        resp = requests.get(
            f"{pr.commits_url}?page={i}&per_page=100",
            headers=PR_COMMITS_HEADER,
        )
        if resp.status_code == 200:
            commits_json.extend(resp.json())
            i += 1
        if resp.status_code in {403, 429}:
            sleep_time = (
                int(resp.headers.get("x-ratelimit-reset")) - time.time()
            )
            if sleep_time > 0:
                logger.warning(
                    "Rate limit exceeded. Sleeping for %s seconds", sleep_time
                )
                time.sleep(sleep_time)
    return commits_json


def get_github(token: str = GH_TOKEN_):
    global _G
    if _G is None:
        auth = Auth.Token(token)
        _G = Github(auth=auth, per_page=100)
    return _G


def get_repo(user: str, repo: str) -> GHRepository:
    g = get_github()
    return g.get_repo(f"{user}/{repo}")


def get_repo_with_model(
    user: str, repo: str, session: Session
) -> tuple[GHRepository, Repository]:
    if (
        session.query(Repository)
        .filter(Repository.user == user, Repository.name == repo)
        .count()
        == 0
    ):
        session.add(Repository(user=user, name=repo))
        session.commit()
    repo_ = get_repo(user, repo)
    return repo_, get_repo_model(user, repo, session)


def stars_per_date(user: str, repo: str):
    repo = get_repo(user, repo)
    date_to_stars = {}

    for star in sorted(
        repo.get_stargazers_with_dates(), key=lambda x: x.starred_at
    ):
        date = star.starred_at.date()
        date_to_stars[date] = date_to_stars.get(date, 0) + 1
    return date_to_stars


def save_stars(user: str, repo: str, session: Session) -> None:
    """
    Save stars information for a repository to the database
    Parameters
    ----------
    user : str
        user or organization name on GitHub
    repo : str
        repository name on GitHub
    session : sqlalchemy.orm.Session
        database session
    """
    gh_repo, repo_model = get_repo_with_model(user, repo, session)

    count = (
        session.query(Stars)
        .filter(
            Stars.repository_name == repo_model.name,
            Stars.repository_user == repo_model.user,
        )
        .count()
    )
    if count == gh_repo.stargazers_count:
        logger.info(
            "Already saved %s stars for %s",
            gh_repo.stargazers_count,
            gh_repo.full_name,
        )
        return
    if count > gh_repo.stargazers_count:
        session.query(Stars).filter(
            Stars.repository_name == repo_model.name,
            Stars.repository_user == repo_model.user,
        ).delete()
        session.commit()
        logger.info(
            "Reset starts because have more saved stars %s than exists %s",
            count,
            gh_repo.stargazers_count,
        )

    stargazers = gh_repo.get_stargazers_with_dates()

    for star in tqdm(
        stargazers, total=gh_repo.stargazers_count, desc=f"Stars {user}/{repo}"
    ):
        ensure_user(star.user.login, session)
        session.merge(
            Stars(
                user=star.user.login,
                date=star.starred_at,
                datetime=star.starred_at,
                repository_user=repo_model.user,
                repository_name=repo_model.name,
            )
        )
    session.commit()
    count_2 = (
        session.query(Stars)
        .filter(
            Stars.repository_name == repo_model.name,
            Stars.repository_user == repo_model.user,
        )
        .count()
    )
    logger.info(
        "Saved %s stars for %s/%s",
        count_2 - count,
        repo_model.user,
        repo_model.name,
    )


def ensure_user(user: str, session: Session) -> None:
    if (
        session.query(GithubUser).filter(GithubUser.username == user).count()
        == 0
    ):
        session.add(GithubUser(username=user))
        session.commit()


def get_pull_request_coauthors(pr: GHPullRequest, session: Session):
    coauthors = set()
    for commit in pr.get_commits():
        if commit.author is not None:
            coauthors.add(commit.author.login)
        else:
            coauthors.add(pr.user.login)
    try:
        coauthors.remove(pr.user.login)
    except KeyError:
        if (
            not pr.title.startswith("test: [Automatic]")
            and pr.user.login not in BOT_SET
        ):
            logger.exception("PR %s author not in coauthors", pr)
    return [
        get_or_create(session, GithubUser, username=coauthor)
        for coauthor in coauthors
    ]


def _get_pr_attributes(pr: GHPullRequest, session: Session):
    return {
        "merge_time": pr.merged_at,
        "close_time": pr.closed_at,
        "last_modification_time": pr.updated_at,
        "title": pr.title,
        "description": pr.body,
        "labels": [
            get_or_create(session, Labels, label=label.name)
            for label in pr.get_labels()
        ],
        # "coauthors": get_pull_request_coauthors(pr, session),
    }


def save_pull_requests(user: str, repo: str, session: Session) -> None:
    """
    Save pull requests information for a repository to the database
    Parameters
    ----------
    user : str
        user or organization name on GitHub
    repo : str
        repository name on GitHub
    session : sqlalchemy.orm.Session
        database session
    """
    gh_repo, repo_model = get_repo_with_model(user, repo, session)

    count = (
        session.query(PullRequests)
        .filter(
            PullRequests.repository_user == repo_model.user,
            PullRequests.repository_name == repo_model.name,
        )
        .count()
    )

    pr_iter = gh_repo.get_pulls(state="all")
    for pr in tqdm(
        pr_iter, total=pr_iter.totalCount, desc=f"Pull Requests {user}/{repo}"
    ):
        ensure_user(pr.user.login, session)
        # check if pull request is already saved and check if there is a need to update
        # merge status and labels
        pull = (
            session.query(PullRequests)
            .filter(
                PullRequests.repository_user == repo_model.user,
                PullRequests.repository_name == repo_model.name,
                PullRequests.pull_request == pr.number,
            )
            .first()
        )
        if pull is None:
            pull = PullRequests(
                user=pr.user.login,
                repository_user=repo_model.user,
                repository_name=repo_model.name,
                open_time=pr.created_at,
                last_modification_time=pr.updated_at.replace(tzinfo=None),
                pull_request=pr.number,
            )
            session.add(pull)

        elif pull.last_modification_time == pr.updated_at.replace(tzinfo=None):
            continue

        for key, value in _get_pr_attributes(pr, session).items():
            setattr(pull, key, value)

        commits_json = get_commits(pr)

        for commit in commits_json:
            # if session.query(PullRequestCommits).get(commit.sha):
            #     continue
            user_login = (
                commit["author"]["login"]
                if commit["author"]
                else pr.user.login
            )
            date = datetime.datetime.fromisoformat(
                commit["commit"]["author"]["date"]
            ).replace(tzinfo=None)
            ensure_user(user_login, session)
            session.merge(
                PullRequestCommits(
                    sha=commit["sha"],
                    user=user_login,
                    date=date,
                    pr_num=pr.number,
                    repository_name=repo_model.name,
                    repository_user=repo_model.user,
                )
            )

        for review in pr.get_reviews():
            if review.state == "PENDING":
                continue
            if session.query(PullRequestReviews).get(review.id):
                continue
            ensure_user(review.user.login, session)
            session.add(
                PullRequestReviews(
                    id=review.id,
                    user=review.user.login,
                    date=review.submitted_at,
                    state=review.state,
                    pr_num=pr.number,
                    repository_name=repo_model.name,
                    repository_user=repo_model.user,
                )
            )

        for comment in pr.get_comments():
            if session.query(PullRequestComments).get(comment.id):
                continue
            ensure_user(comment.user.login, session)
            session.merge(
                PullRequestComments(
                    id=comment.id,
                    user=comment.user.login,
                    date=comment.created_at,
                    pr_num=pr.number,
                    repository_name=repo_model.name,
                    repository_user=repo_model.user,
                )
            )

    session.commit()
    count_2 = (
        session.query(PullRequests)
        .filter(
            PullRequests.repository_user == repo_model.user,
            PullRequests.repository_name == repo_model.name,
        )
        .count()
    )

    logger.info(
        "Saved %s pull requests for %s", count_2 - count, gh_repo.full_name
    )


def save_issues(user: str, repo: str, session: Session) -> None:
    """
    Save issues information for a repository to the database

    Parameters
    ----------
    user : str
        user or organization name on GitHub
    repo : str
        repository name on GitHub
    session : sqlalchemy.orm.Session
        database session
    """
    gh_repo, repo_model = get_repo_with_model(user, repo, session)

    count = (
        session.query(Issues)
        .filter(
            Issues.repository_user == repo_model.user,
            Issues.repository_name == repo_model.name,
        )
        .count()
    )
    issue_iter = gh_repo.get_issues(state="all")
    for issue in tqdm(
        issue_iter, total=issue_iter.totalCount, desc=f"Issues {user}/{repo}"
    ):
        if (
            session.get(
                PullRequests,
                {
                    "repository_user": repo_model.user,
                    "repository_name": repo_model.name,
                    "pull_request": issue.number,
                },
            )
            is not None
        ):
            continue

        issue_ob = (
            session.query(Issues)
            .filter(
                Issues.repository_user == repo_model.user,
                Issues.repository_name == repo_model.name,
                Issues.issue == issue.number,
            )
            .first()
        )
        if issue_ob is None and issue.pull_request is not None:
            continue

        if issue_ob is None:
            ensure_user(issue.user.login, session)
            issue_ob = Issues(
                user=issue.user.login,
                repository_user=repo_model.user,
                repository_name=repo_model.name,
                issue=issue.number,
                open_time=issue.created_at,
            )
            session.add(issue_ob)

        elif issue_ob.last_modification_time == issue.updated_at.replace(
            tzinfo=None
        ):
            continue

        issue_ob.title = issue.title
        issue_ob.description = issue.body
        issue_ob.close_time = issue.closed_at
        issue_ob.last_modification_time = issue.updated_at.replace(tzinfo=None)
        issue_ob.labels = [
            get_or_create(session, Labels, label=label.name)
            for label in issue.get_labels()
        ]

        for comment in issue.get_comments():
            if session.query(IssueComment).get(comment.id):
                continue
            ensure_user(comment.user.login, session)
            session.merge(
                IssueComment(
                    id=comment.id,
                    user=comment.user.login,
                    date=comment.created_at,
                    issue=issue.number,
                    repository_name=repo_model.name,
                    repository_user=repo_model.user,
                )
            )
    session.commit()
    count_2 = (
        session.query(Issues)
        .filter(
            Issues.repository_user == repo_model.user,
            Issues.repository_name == repo_model.name,
        )
        .count()
    )
    logger.info("Saved %s issues for %s", count_2 - count, gh_repo.full_name)


def update_artifact_download(user: str, repo: str, session: Session):
    gh_repo, repo_model = get_repo_with_model(user, repo, session)

    releases = gh_repo.get_releases()

    for release in tqdm(
        releases,
        total=releases.totalCount,
        desc=f"Artifact downloads {user}/{repo}",
    ):
        if release.prerelease:
            continue
        release_model = get_or_create(
            session,
            Release,
            repository_name=repo_model.name,
            repository_user=repo_model.user,
            release_tag=release.tag_name,
        )
        for asset in release.get_assets():
            if asset.name.endswith(".sh"):
                platform = "Linux"
            elif asset.name.endswith(".exe"):
                platform = "Windows"
            elif asset.name.endswith(".pkg"):
                platform = "macOS"
            else:
                continue
            session.merge(
                ArtifactDownloads(
                    release_tag=release_model.release_tag,
                    repository_name=repo_model.name,
                    repository_user=repo_model.user,
                    artifact_name=asset.name,
                    download_count=asset.download_count,
                    platform=platform,
                )
            )
    session.commit()
