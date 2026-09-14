# Muninn Bootstrap

Before doing project work, ensure Muninn is available and current:

```bash
if [[ ! -d "$HOME/muninn/.git" ]]; then
  git clone https://github.com/jm1024/muninn.git "$HOME/muninn"
else
  git -C "$HOME/muninn" fetch origin
  if git -C "$HOME/muninn" show-ref --verify --quiet refs/heads/main; then
    git -C "$HOME/muninn" pull --ff-only
  elif git -C "$HOME/muninn" show-ref --verify --quiet refs/remotes/origin/main; then
    git -C "$HOME/muninn" checkout --track origin/main
  fi
fi

muninn_key="$HOME/.config/muninn/git-crypt-key"
if command -v git-crypt >/dev/null 2>&1 && [[ -f "$muninn_key" ]]; then
  git -C "$HOME/muninn" crypt unlock "$muninn_key"
fi
```

Then read:

- `$HOME/muninn/AGENTS.md`

After loading Muninn's instructions, continue with the user's task in the
original project directory.
