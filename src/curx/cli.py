import argparse

from curx.core.config import get_settings
from curx.core.database import create_db_engine, create_session_factory
from curx.services.identity_service import IdentityError, bootstrap_admin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Curx administration commands.")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser(
        "bootstrap-admin",
        help="Create the first tenant, administrator, and one-time access key.",
    )
    bootstrap.add_argument("--tenant-name", default="Curx")
    bootstrap.add_argument("--tenant-slug", default="curx")
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name")
    bootstrap.add_argument("--expires-days", type=int, default=365)
    bootstrap.add_argument(
        "--without-default-space",
        action="store_true",
        help="Do not create the initial knowledge space.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command != "bootstrap-admin":
        return 2
    if args.expires_days <= 0:
        raise SystemExit("--expires-days must be greater than zero.")

    settings = get_settings()
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            try:
                tenant, user, access_key, raw_key = bootstrap_admin(
                    db,
                    tenant_name=args.tenant_name,
                    tenant_slug=args.tenant_slug,
                    username=args.username,
                    display_name=args.display_name or args.username,
                    expires_in_days=args.expires_days,
                    create_default_space=not args.without_default_space,
                )
            except IdentityError as exc:
                raise SystemExit(f"{exc.code}: {exc.message}") from exc
    finally:
        engine.dispose()

    print(f"Tenant: {tenant.name} ({tenant.slug})")
    print(f"Administrator: {user.username}")
    print(f"Key prefix: {access_key.prefix}")
    print("Curx access key (shown once):")
    print(raw_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
