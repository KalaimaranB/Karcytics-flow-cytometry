import os
import shutil
from pathlib import Path

def sync():
    # First check if running in CI (where we check it out to external_core)
    core_dir = Path("external_core")
    
    # Fallback to local development path
    if not core_dir.exists():
        core_dir = Path("../Karcytics")
        
    if not core_dir.exists():
        print(f"Warning: Core directory {core_dir.absolute()} not found. Skipping sync.")
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
        shutil.copy2(install_src, install_dest)
        print(f"Copied {install_src} to {install_dest}")
    
    # Copy images
    if img_src.exists():
        if img_dest.exists():
            shutil.rmtree(img_dest)
        img_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(img_src, img_dest)
        print(f"Copied images from {img_src} to {img_dest}")

if __name__ == "__main__":
    sync()
