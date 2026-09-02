import os
import sys

import yaml

try:
    from schema import ScenarioLabel
except ImportError:
    from scenarios.schema import ScenarioLabel


def main():
    labels_dir = "scenarios/labels"
    if not os.path.exists(labels_dir):
        if os.path.exists("labels"):
            labels_dir = "labels"
        else:
            print(f"Directory {labels_dir} does not exist.")
            sys.exit(1)

    failed = False
    for filename in sorted(os.listdir(labels_dir)):
        if not filename.endswith(".yaml"):
            continue

        filepath = os.path.join(labels_dir, filename)
        try:
            with open(filepath, "r") as f:
                data = yaml.safe_load(f)
            ScenarioLabel(**data)
            print(f"✅ {filename} passed validation.")
        except Exception as e:  # noqa: BLE001
            print(f"❌ {filename} failed validation:\n{e}")
            failed = True

    if failed:
        sys.exit(1)
    else:
        print("All labels passed schema validation.")


if __name__ == "__main__":
    main()
