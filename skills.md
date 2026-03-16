# Agent Skills

Add skills below. Each skill tells the agent how to handle a specific type of request.
Skills are appended to the system prompt when the agent starts.

---

## git_status
When the user asks about git changes, staged files, or repo status, run:
`git status` and `git log --oneline -5`

## disk_usage
When the user asks about disk space or storage, run:
`df -h` for overall usage and `du -sh *` for folder sizes in the current directory.

## process_monitor
When the user asks what is running or using resources, run:
`ps aux | sort -rk 3 | head -20` to show top CPU-consuming processes.

## find_file
When the user wants to find a file by name, use:
`find . -name "<filename>" 2>/dev/null`

## environment
When the user asks about environment variables or PATH, run:
`env | sort`

## web_browse
When the user asks about an external URL or wants to fetch content from a website, use:
`curl -sL --max-time 10 "<url>" | sed 's/<[^>]*>//g' | sed '/^[[:space:]]*$/d' | head -200`

This fetches the page and strips HTML tags to return readable plain text. Use the exact URL provided by the user. If the content is too long or unclear, summarize the most relevant parts.
