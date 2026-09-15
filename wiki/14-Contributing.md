# ❤️ Contributing

We welcome contributions from everyone! Whether it's fixing a bug, adding a feature, improving documentation, or just giving feedback — every contribution makes this project better.

---

## Ways to Contribute

### 🐛 Report Bugs
Found a bug? [Open an issue](https://github.com/pdrajan0x/AutoCutClips/issues/new) with:
- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, Python version, GPU)
- Error logs or screenshots

### 💡 Suggest Features
Have an idea? Open an issue with the `enhancement` label describing:
- What problem it solves
- How you imagine it working
- Example use cases

### 🔧 Submit Code
1. **Fork** the repository
2. **Create a branch** for your feature: `git checkout -b feature/my-feature`
3. **Make your changes** and test them
4. **Commit** with clear messages: `git commit -m "Add: my awesome feature"`
5. **Push** to your fork: `git push origin feature/my-feature`
6. **Open a Pull Request** with a description of your changes

### 📝 Improve Documentation
- Fix typos or unclear instructions
- Add examples and use cases
- Translate documentation to other languages
- Update the wiki

---

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR-USERNAME/AutoCutClips.git
cd AutoCutClips

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up API keys
cp .env.sample .env
# Edit .env with your keys

# 4. Run a test
python -m app.cli --url "https://youtube.com/watch?v=TEST_VIDEO" --clips 1 --no-bgm --no-broll
```

---

## Project Structure

```text
AutoCutClips/
├── app/
│   ├── cli.py                # CLI entry point (python -m app.cli)
│   ├── clipping/
│   │   ├── config.py         # Master configuration & argparse
│   │   ├── runner.py         # Pipeline orchestrator
│   │   ├── story_runner.py   # Story Clip Mode orchestrator
│   │   ├── story/            # Story mode helper modules
│   │   ├── engine/           # Download → Transcribe → Gemini/NVIDIA AI
│   │   └── studio/           # Video render engine modules
│   ├── uploaders/            # YouTube + Instagram upload & scheduling logic
│   ├── tracker/              # YouTube Tracker web app
│   └── web/                  # Web API for the Studio (static pages in docs/studio)
├── pyproject.toml            # Dependencies, metadata & console scripts
├── .env.sample                # API key template
└── wiki/                      # This documentation
```

---

## Code Style

- **Python**: Follow PEP 8 guidelines
- **Commits**: Use descriptive commit messages with prefixes (`Add:`, `Fix:`, `Refactor:`, `Docs:`)
- **Documentation**: Add docstrings to new functions and update the wiki if needed

---

## Other Ways to Support

Even if you don't code, you can still help:

- ⭐ **Star** the repository on GitHub
- 🍴 **Fork** and experiment with the code
- 📢 **Share** the project with others
- 💬 **Give feedback** on what works and what doesn't
- 📖 **Write tutorials** or blog posts about using the tool

---

## License

This project is **open source**. Feel free to use, modify, and distribute.

---

## See Also

- [Getting Started](Getting-Started) — Setup guide
- [CLI Reference](CLI-Reference) — All available options
- [Troubleshooting & FAQ](Troubleshooting-and-FAQ) — Common issues
