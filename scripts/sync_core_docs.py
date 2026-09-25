import shutil
from pathlib import Path


def sync():
    # First check if running in CI (where we check it out to external_core)
    core_dir = Path("external_core")

    # Fallback to local development path
    if not core_dir.exists():
        core_dir = Path("../Karcytics")

    if not core_dir.exists():
        print(f"Warning: Core directory {core_dir.absolute()} not found. Skipping sync.")  # noqa: T201
        return

    install_src = core_dir / "docs" / "user" / "06_Installation.md"
    install_dest = Path("docs") / "user" / "14_INSTALLATION.md"

    # In core, the images are in docs/user/image/06_Installation
    img_src = core_dir / "docs" / "user" / "image" / "06_Installation"
    # When rendered as docs/user/14_INSTALLATION.md, relative path `image/...`
    # looks in docs/user/image/
    img_dest = Path("docs") / "user" / "image" / "06_Installation"

    # Copy markdown
    install_dest.parent.mkdir(parents=True, exist_ok=True)
    if install_src.exists():
        with open(install_src, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Rewrite links for the flow module documentation structure
        content = content.replace("02_Getting_Started.md", "01_GETTING_STARTED.md")
        content = content.replace("05_FAQ_Troubleshooting.md", "13_TROUBLESHOOTING.md")
        content = content.replace("07_Plugin_Store_and_Security.md", "https://kalaimaranb.github.io/Karcytics/user/07_Plugin_Store_and_Security/")
        
        with open(install_dest, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"Copied and processed {install_src} to {install_dest}")  # noqa: T201

    # Copy images
    if img_src.exists():
        if img_dest.exists():
            shutil.rmtree(img_dest)
        img_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(img_src, img_dest)
        print(f"Copied images from {img_src} to {img_dest}")  # noqa: T201


if __name__ == "__main__":
    sync()
