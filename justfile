font := "figtree"

# Generate the README and SVGs, fetching and compressing the avatar each time.
generate avatar_url="https://bafkreiezqlkiu2ypbvlih7sjz72owpz54uisjcdjhnvieajoj66njptgia.ipfs.inbrowser.link/": _setup
    .venv/bin/python scripts/build_readme.py --avatar-url {{ quote(avatar_url) }} --font {{ quote(font) }}

# Bootstrap isolated, pinned dependencies for reproducible output.
[private]
_setup:
    python3 -m venv .venv
    .venv/bin/python -m pip install --quiet --disable-pip-version-check -r scripts/requirements.txt
