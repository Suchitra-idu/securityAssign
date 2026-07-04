"""
mkdocs-macros hooks for this docs site.

The main job of this file is to give the docs a single `src()` macro that
produces a link into the source tree on GitHub. That lets every doc page
reference concrete files and line ranges without hard-coding the repo URL
in ~180 markdown links, and without breaking when someone changes the URL.

Usage in markdown:

    {{ src("auth_service/src/auth_service/application/tokens.py") }}
        → "tokens.py" linked to the file on GitHub.

    {{ src("auth_service/src/auth_service/application/tokens.py", lines="23-30") }}
        → "tokens.py:23-30" linked to those lines.

    {{ src("shared_security/tests/test_tokens.py",
           text="test_algorithm_confusion_hs256_rejected") }}
        → custom link text.

    {{ src("flags.md", anchor="1-timing-safe-unknown-user-login", text="flag 1") }}
        → link with a non-line anchor.

Configuration:

- repo_url is read from mkdocs.yml. Update it to point at the real GitHub
  repository.
- branch defaults to "main". Override via `extra.branch` in mkdocs.yml.
"""


def define_env(env):
    repo_url = (env.conf.get("repo_url") or "").rstrip("/")
    branch = env.conf.get("extra", {}).get("branch", "main")

    @env.macro
    def src(path, text=None, lines=None, anchor=None):
        filename = path.rsplit("/", 1)[-1]
        if text is None:
            text = f"{filename}:{lines}" if lines else filename

        url = f"{repo_url}/blob/{branch}/{path}"
        if lines:
            parts = lines.split("-", 1)
            url += f"#L{parts[0]}"
            if len(parts) == 2:
                url += f"-L{parts[1]}"
        elif anchor:
            url += f"#{anchor}"
        return f"[{text}]({url})"
