"""Read-only diagnostic for one workspace image using the installed model."""
from pathlib import Path
import sys
import json
import argparse
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.analysis import LocalVision
from app.config import ROOT, TEMP

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--focus', action='store_true')
    args = parser.parse_args()
    image = args.image.resolve()
    image.relative_to(ROOT)
    if not image.is_file():
        parser.error('Image is missing')
    directory = TEMP / ('visioncheck-' + uuid.uuid4().hex)
    directory.mkdir()
    prompt = ('Locate the face center of the visible speaking/main character. Return JSON '
              '{"x":normalized horizontal position,"y":normalized vertical position,"confidence":number}.'
              if args.focus else 'Describe only these images in Russian. Return JSON '
              '{"summary":"actual visible actions","credit_montage":boolean,"continuous_narrative":boolean}.')
    with LocalVision(directory, lambda: False) as vision:
        print(json.dumps(vision.query(prompt, image, max_tokens=400), ensure_ascii=False))

if __name__ == '__main__':
    main()
