# Setup

Get one of these two running on your own laptop before class.
Both are terminal agents and the session works with either.

- **Option 1, Antigravity CLI: free for students. Recommended. Start here.**
- **Option 2, Claude Code: paid subscription.** It is what will be on the screen, and
  it gives you the more advanced models.

I prepared the course materials in early August 2026, when Claude Pro was the only option I
could recommend without caveats. Google reopened its free student plan on August
19, so now there is a free path that is good enough to start with.

---

## Option 1: Antigravity CLI (free for students, recommended)

Google's terminal agent, and what Gemini CLI became.

1. **Claim the student plan**: one free year of Google AI Pro at
   [gemini.google/students](https://gemini.google/students/)
   ([announcement](https://blog.google/innovation-and-ai/products/gemini-app/student-offer-google-ai/)).
   Verify with your Yale email through SheerID. Redeem by December 31, 2026. It
   renews at 19.99 USD/month after the free year, so note the date.

2. **Install** ([docs](https://antigravity.google/download#antigravity-cli)):

   ```
   curl -fsSL https://antigravity.google/cli/install.sh | bash    # macOS, Linux
   irm https://antigravity.google/cli/install.ps1 | iex           # Windows PowerShell
   ```

3. **Log in** with the Google account holding the student plan.

4. **Run it** from whatever folder you want to work in:

   ```
   cd your-project-folder
   agy
   ```

---

## Option 2: Claude Code (paid)

The tool the session is built around, so my screen will match your terminal. The
free Claude.ai plan does not include it. Claude Code requires a paid subscription.

1. **Subscribe** to a plan at
   [claude.com/pricing](https://claude.com/pricing). For example, Pro plan, 20 USD/month, 

2. **Install** ([docs](https://code.claude.com/docs/en/setup)):

   ```
   curl -fsSL https://claude.ai/install.sh | bash      # macOS, Linux, WSL
   irm https://claude.ai/install.ps1 | iex             # Windows PowerShell
   ```

3. **Run it**, and log in through the browser when it prompts:

   ```
   cd your-project-folder
   claude
   ```

---

You are set up when you get a prompt in your terminal, can ask it something like
`what files are in this folder?`, and get an answer.

## Useful commands

Type these inside the agent, not in your normal shell.

| Command | What it does |
|---|---|
| `/help` | Every command the tool has. The only list that is never out of date. |
| `/model` | Switch which model you are talking to. |
| `/effort` | How hard the model thinks first. More is slower and costlier, better on hard problems. |
| `/usage` | What you have spent and what is left. |
| `/clear` | Start a fresh conversation. Do this between unrelated tasks. |
| `/compact` | Summarize the conversation to free up room, when a long session starts to feel forgetful. Claude Code only. |
| `/resume` | Reopen an earlier conversation. |
| `/rewind` | Undo. Rolls the conversation, and the edits it made, back to an earlier point. |
| `/exit` | Quit. |

Two keys worth knowing:

- **Esc** stops the agent mid-answer, which you will want the moment you see it
  heading somewhere wrong. `Ctrl+C` twice force quits.
- **Shift+Tab** cycles how much it is allowed to do on its own, including plan
  mode, where it writes a plan and waits instead of editing your files. Plan mode
  is also `/plan` in Claude Code and `/planning` in Antigravity, and we use it in
  class.

## If you get stuck

Copy the exact error message and paste it into whatever AI tool you already have,
Google Gemini, Claude, ChatGPT. Installation errors are the easiest thing in the
world to ask about, and getting one unstuck is a fair warm-up for the session.
