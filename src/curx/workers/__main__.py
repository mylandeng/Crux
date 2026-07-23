from arq.worker import run_worker

from curx.workers.ingestion import WorkerSettings


def main() -> None:
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
