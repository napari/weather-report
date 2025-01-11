# noqa: INP001
import datetime
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tqdm import tqdm

from napari_dashboard.db_schema.github import PullRequestCommits
from napari_dashboard.db_update.github import (
    ensure_user,
    get_commits,
    get_repo_with_model,
)
from napari_dashboard.db_update.util import setup_cache
from napari_dashboard.get_webpage.gdrive import fetch_database

db_path = Path(__file__).parent.parent / "dashboard.db"

PR_COMMITS_HEADER = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ.get('GH_TOKEN_')}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def main():
    fetch_database()

    setup_cache()

    engine = create_engine(f"sqlite:///{db_path.absolute()}")

    with Session(engine) as session:
        # session.query(PullRequestCommits).delete()
        session.commit()
        for user, repo in (
            ("napari", "napari"),
            ("napari", "docs"),
            ("napari", "npe2"),
        ):
            gh_repo, repo_model = get_repo_with_model(user, repo, session)
            pr_iter = gh_repo.get_pulls(state="all")
            for pr in tqdm(
                pr_iter,
                total=pr_iter.totalCount,
                desc=f"Pull Requests {user}/{repo}",
            ):
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
            session.commit()


if __name__ == "__main__":
    main()
