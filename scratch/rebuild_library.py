import re
from pathlib import Path

# 1. Update library.js HTML generation
lib_path = Path("app/static/library.js")
lib = lib_path.read_text("utf-8")

lib = lib.replace("wrapper.className='project-card-wrap'", "wrapper.className='item-card-wrap'")
lib = lib.replace("card.className='project-card'", "card.className='item-card'")
lib = lib.replace("mark.className=`project-monogram color-${(index%3)+1}`", "mark.className=`card-icon color-${(index%3)+1}`")
lib = lib.replace("name.className=''", "name.className='card-title'") # doesn't exist, we will inject it
lib = lib.replace("name.textContent=project.title;", "name.textContent=project.title; name.className='card-title';")
lib = lib.replace("meta.textContent", "meta.className='card-meta'; meta.textContent")
lib = lib.replace("action.className='card-action'", "action.className='btn-text card-actions'")

lib = lib.replace("card.className='episode-card'", "card.className='item-card'")
lib = lib.replace("number.className='episode-index'", "number.className='card-icon'")
lib = lib.replace("name.textContent=episode.title;", "name.textContent=episode.title; name.className='card-title';")
lib = lib.replace("actions.className='episode-card-actions'", "actions.className='card-actions'")
lib = lib.replace("edit.className='secondary-button'", "edit.className='btn-secondary'")
lib = lib.replace("review.className='text-button'", "review.className='btn-text'")

lib_path.write_text(lib, "utf-8")
print("Library patched")
