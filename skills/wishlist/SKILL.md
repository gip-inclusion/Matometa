# Wishlist Skill

Log capability requests, tool wishes, and improvement ideas.

Use this skill when you:
- Wish you had a tool or capability you don't have
- Think a task would be easier with different permissions
- Have ideas for improving workflows or knowledge
- Notice gaps in documentation or skills

## Usage

```bash
# Add a wish
python skills/wishlist/scripts/wishlist.py add \
    --category "tool" \
    --title "WebFetch for documentation sites" \
    --description "Would help when needing to read external API docs"

# List recent wishes
python skills/wishlist/scripts/wishlist.py list

# List by category
python skills/wishlist/scripts/wishlist.py list --category tool
```

## Categories

- `tool` - Missing or restricted tool capabilities
- `knowledge` - Gaps in knowledge files
- `skill` - Ideas for new skills
- `workflow` - Process improvements
- `other` - Anything else

## Examples

**Tool wish:**
```bash
python skills/wishlist/scripts/wishlist.py add \
    --category "tool" \
    --title "curl to external documentation" \
    --description "Needed to fetch Django docs to understand QuerySet API"
```

**Knowledge gap:**
```bash
python skills/wishlist/scripts/wishlist.py add \
    --category "knowledge" \
    --title "Metabase SQL dialect reference" \
    --description "Unclear which SQL functions are available in Metabase queries"
```

**Workflow idea:**
```bash
python skills/wishlist/scripts/wishlist.py add \
    --category "workflow" \
    --title "Auto-save report drafts" \
    --description "Would help avoid losing work on long reports"
```
