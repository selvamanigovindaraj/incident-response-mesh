from config.settings import load_settings


def main() -> int:
    load_settings("hello-world")
    print("Hello, world!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
