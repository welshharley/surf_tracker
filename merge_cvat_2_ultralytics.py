from __future__ import annotations

import random
import shutil
from pathlib import Path
from typing import List

# =========================
# Settings
# =========================
CVAT_EXPORTS_DIR = Path("CVAT_exports")
OUTPUT_DIR = Path("ultralytics_dataset")
TRAIN_RATIO = 0.8
RANDOM_SEED = 42

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def read_obj_names(export_dir: Path) -> List[str]:
    obj_names = export_dir / "obj.names"
    if not obj_names.exists():
        raise FileNotFoundError(f"Missing obj.names in {export_dir}")
    names = [line.strip() for line in obj_names.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names:
        raise ValueError(f"obj.names is empty in {export_dir}")
    return names


def find_obj_train_data(export_dir: Path) -> Path:
    data_dir = export_dir / "obj_train_data"
    if data_dir.exists() and data_dir.is_dir():
        return data_dir
    raise FileNotFoundError(f"Missing obj_train_data in {export_dir}")


def find_export_dirs(root: Path) -> List[Path]:
    """
    Returns immediate subfolders inside CVAT_EXPORTS_DIR that look like CVAT YOLO exports.
    """
    if not root.exists():
        raise FileNotFoundError(f"Folder not found: {root.resolve()}")

    export_dirs = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "obj.names").exists() and (child / "obj_train_data").exists():
            export_dirs.append(child)

    if not export_dirs:
        raise FileNotFoundError(
            f"No valid CVAT export folders found inside {root.resolve()}.\n"
            f"Each folder should contain at least:\n"
            f"  - obj.names\n"
            f"  - obj_train_data/\n"
        )
    return export_dirs


def validate_class_lists(export_dirs: List[Path]) -> List[str]:
    all_names = [read_obj_names(d) for d in export_dirs]
    first = all_names[0]
    for d, names in zip(export_dirs[1:], all_names[1:]):
        if names != first:
            raise ValueError(
                f"Class mismatch found.\n"
                f"Reference classes: {first}\n"
                f"Different classes in: {d}\n"
                f"Found: {names}"
            )
    return first


def collect_pairs(export_dirs: List[Path]) -> List[dict]:
    """
    Collect image/label pairs from all export directories.
    Each pair gets a unique prefixed filename based on export folder name.
    """
    pairs = []

    for export_dir in export_dirs:
        prefix = export_dir.name
        data_dir = find_obj_train_data(export_dir)

        image_files = sorted([p for p in data_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS])

        if not image_files:
            print(f"Warning: no images found in {data_dir}")
            continue

        for img_path in image_files:
            stem = img_path.stem
            label_path = data_dir / f"{stem}.txt"

            new_stem = f"{prefix}_{stem}"
            pairs.append({
                "src_image": img_path,
                "src_label": label_path,
                "new_stem": new_stem,
                "image_suffix": img_path.suffix.lower(),
            })

    if not pairs:
        raise RuntimeError("No image files found in any export.")
    return pairs


def prepare_output_dirs(output_dir: Path) -> None:
    if output_dir.exists():
        print(f"Removing existing output folder: {output_dir.resolve()}")
        shutil.rmtree(output_dir)

    for sub in [
        output_dir / "images" / "train",
        output_dir / "images" / "val",
        output_dir / "labels" / "train",
        output_dir / "labels" / "val",
    ]:
        sub.mkdir(parents=True, exist_ok=True)


def copy_pair(pair: dict, split: str, output_dir: Path) -> None:
    img_dst = output_dir / "images" / split / f"{pair['new_stem']}{pair['image_suffix']}"
    lbl_dst = output_dir / "labels" / split / f"{pair['new_stem']}.txt"

    shutil.copy2(pair["src_image"], img_dst)

    if pair["src_label"].exists():
        shutil.copy2(pair["src_label"], lbl_dst)
    else:
        # valid for images with no annotations
        lbl_dst.write_text("", encoding="utf-8")


def write_data_yaml(output_dir: Path, class_names: List[str]) -> None:
    yaml_path = output_dir / "data.yaml"

    lines = [
        f"path: {output_dir.resolve()}",
        "train: images/train",
        "val: images/val",
        "",
        "names:",
    ]
    for idx, name in enumerate(class_names):
        lines.append(f"  {idx}: {name}")

    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    random.seed(RANDOM_SEED)

    export_dirs = find_export_dirs(CVAT_EXPORTS_DIR)
    print("Found CVAT export folders:")
    for d in export_dirs:
        print(f"  - {d}")

    class_names = validate_class_lists(export_dirs)
    print(f"\nClasses: {class_names}")

    pairs = collect_pairs(export_dirs)
    print(f"Collected {len(pairs)} image/label pairs")

    random.shuffle(pairs)

    train_count = int(len(pairs) * TRAIN_RATIO)
    train_pairs = pairs[:train_count]
    val_pairs = pairs[train_count:]

    prepare_output_dirs(OUTPUT_DIR)

    for pair in train_pairs:
        copy_pair(pair, "train", OUTPUT_DIR)

    for pair in val_pairs:
        copy_pair(pair, "val", OUTPUT_DIR)

    write_data_yaml(OUTPUT_DIR, class_names)

    print("\nDone.")
    print(f"Output dataset: {OUTPUT_DIR.resolve()}")
    print(f"Train images: {len(train_pairs)}")
    print(f"Val images:   {len(val_pairs)}")
    print(f"data.yaml:    {(OUTPUT_DIR / 'data.yaml').resolve()}")


if __name__ == "__main__":
    main()
