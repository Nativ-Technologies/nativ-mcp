"""Build the public submission ZIP. Never includes backend code or credentials."""
import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1] / 'plugin'
parser = argparse.ArgumentParser()
parser.add_argument('output',type=Path)
args = parser.parse_args()
manifest=json.loads((ROOT/'plugin.json').read_text())
assert 1 <= len(manifest['extensions']['com.openai']['interface']['shortDescription']) <= 30, 'Directory subtitle must fit 30 characters'
mcp=json.loads((ROOT/'mcp.json').read_text())
auth=mcp['mcpServers']['nativ']['extensions']['com.openai']['auth']
assert auth['type']=='oauth' and auth['client']['tokenEndpointAuthMethod']=='none'
assert auth['baseScopes']==['nativ:localize']
assert mcp['mcpServers']['nativ']['url']=='https://mcp.usenativ.com/chatgpt/mcp'
assert len(manifest['extensions']['com.openai']['review']['test_cases']['positive'])>=5
assert len(manifest['extensions']['com.openai']['review']['test_cases']['negative'])>=3
files=[ROOT/'plugin.json',ROOT/'mcp.json',*sorted((ROOT/'assets').glob('*.png'))]
for file in files:
 assert file.is_file() and not file.is_symlink()
 for forbidden in ['clientSecret','nativ_your_api_key','Authorization: Bearer','BEGIN PRIVATE KEY']:
  if file.suffix=='.json':assert forbidden not in file.read_text()
args.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as archive:
 for file in files:archive.write(file,file.relative_to(ROOT))
print(f'Packaged {len(files)} files: {args.output}')
