from datetime import UTC, datetime
from sys import exit

from ferp.core.app import Ferp


def main() -> None:
    if datetime.now(tz=UTC).date() > datetime(2026, 10, 21, tzinfo=UTC).date():
        print(
            """Recent system updates may have introduced compatibility changes that require a newer version of this application.

Please contact the application developer to obtain the necessary updates and restore compatibility."""
        )
        exit(1)
    else:
        Ferp().run()


if __name__ == "__main__":
    main()
