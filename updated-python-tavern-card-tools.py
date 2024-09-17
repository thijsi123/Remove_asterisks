import os
import platform
import logging
from flask import Flask, request, redirect, url_for, render_template_string, send_file, abort
import json
import base64
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import zipfile
import io

app = Flask(__name__)

# Detect the platform and set the paths accordingly
if platform.system() == "Linux" and "ANDROID_STORAGE" in os.environ:
    # Assuming Termux on Android
    app.config['UPLOAD_FOLDER'] = '/data/data/com.termux/files/home/uploads'
    app.config['PROCESSED_FOLDER'] = '/data/data/com.termux/files/home/processed'
elif platform.system() == "Windows":
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
    app.config['PROCESSED_FOLDER'] = os.path.join(os.getcwd(), 'processed')
elif platform.system() == "Linux":
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
    app.config['PROCESSED_FOLDER'] = os.path.join(os.getcwd(), 'processed')
elif platform.system() == "Darwin":
    # macOS
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
    app.config['PROCESSED_FOLDER'] = os.path.join(os.getcwd(), 'processed')
else:
    # Default to the directory where the script is located for other/unsupported platforms
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(script_dir, 'uploads')
    app.config['PROCESSED_FOLDER'] = os.path.join(script_dir, 'processed')

# Ensure directories exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

if not os.path.exists(app.config['PROCESSED_FOLDER']):
    os.makedirs(app.config['PROCESSED_FOLDER'])

TEXT_KEY_PNG = "Chara"

logging.basicConfig(level=logging.DEBUG)

def remove_paired_asterisks(input_str: str) -> str:
    if input_str is None:
        return input_str

    input_chars = list(input_str)
    AST = '*'
    BRK = '\n'
    pos_to_elim = []
    detecting_pair = False
    pair_start_index = 0

    for i, ch in enumerate(input_chars):
        if ch == AST:
            if i + 1 < len(input_chars) and input_chars[i + 1] == AST:
                continue
            if i > 0 and input_chars[i - 1] == AST:
                continue

            if not detecting_pair:
                detecting_pair = True
                pair_start_index = i
            else:
                pos_to_elim.append(pair_start_index)
                pos_to_elim.append(i)
                detecting_pair = False

        if ch == BRK:
            detecting_pair = False

    result = ''.join(ch for i, ch in enumerate(input_chars) if i not in pos_to_elim)
    return result

def deasterisk_tavern_card(card: dict):
    def de8(x: str) -> str:
        return remove_paired_asterisks(x) if x is not None else None

    for field in ['description', 'personality', 'scenario', 'first_mes', 'mes_example']:
        card['data'][field] = de8(card['data'].get(field))

    if 'character_book' in card['data'] and card['data']['character_book']:
        for entry in card['data']['character_book'].get('entries', []):
            entry['content'] = de8(entry.get('content'))

    if 'alternate_greetings' in card['data'] and card['data']['alternate_greetings']:
        card['data']['alternate_greetings'] = [de8(g) for g in card['data']['alternate_greetings']]

def read_png_metadata(file_path: str) -> str:
    try:
        with Image.open(file_path) as img:
            metadata = img.info
        for key in [TEXT_KEY_PNG, TEXT_KEY_PNG.lower(), TEXT_KEY_PNG.upper()]:
            if key in metadata:
                return metadata[key]
    except Exception as e:
        logging.error(f"Error reading PNG metadata: {e}")
    return None

def write_png_metadata(original_file: str, new_file: str, chara_data: str):
    try:
        with Image.open(original_file) as img:
            metadata = PngInfo()
            for key, value in img.info.items():
                if key.lower() != TEXT_KEY_PNG.lower():
                    metadata.add_text(key, value)
            metadata.add_text(TEXT_KEY_PNG, chara_data)
            img.save(new_file, "PNG", pnginfo=metadata)
    except Exception as e:
        logging.error(f"Error writing PNG metadata: {e}")

def deasterisk_tavern_file(png_path: str, save_path: str):
    chara_data = read_png_metadata(png_path)
    if not chara_data:
        return "Error: No 'Chara' metadata found in the PNG file."

    try:
        card_data = json.loads(base64.b64decode(chara_data).decode('utf-8'))
    except Exception as e:
        logging.error(f"Base64 decoding failed: {e}")
        try:
            card_data = json.loads(chara_data)
        except Exception as e:
            logging.error(f"JSON parsing failed: {e}")
            return f"Failed to parse metadata as JSON: {e}"

    deasterisk_tavern_card(card_data)

    new_file_name = os.path.join(save_path, f"de8_{os.path.basename(png_path)}")
    try:
        new_chara_data = json.dumps(card_data)
        new_chara_data_encoded = base64.b64encode(new_chara_data.encode('utf-8')).decode('utf-8')
        write_png_metadata(png_path, new_file_name, new_chara_data_encoded)
    except Exception as e:
        logging.error(f"Error during PNG file processing: {e}")
        return f"Error during PNG file processing: {e}"

    return new_file_name

@app.route('/')
def index():
    html_content = '''
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
        <title>Tavern Card Tools</title>
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css">
      </head>
      <body>
        <div class="container">
          <h1 class="mt-5">Tavern Card Tools</h1>
          <p class="lead">Select PNG files to deasterisk:</p>
          <form method="post" enctype="multipart/form-data" action="/upload">
            <div class="form-group">
              <input type="file" class="form-control-file" id="files" name="files" multiple>
            </div>
            <button type="submit" class="btn btn-primary">Upload and Process</button>
          </form>
        </div>
      </body>
    </html>
    '''
    return render_template_string(html_content)

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files' not in request.files:
        logging.error("No file part in the request")
        return redirect(request.url)

    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        logging.error("No selected files")
        return redirect(request.url)

    processed_files = []
    for file in files:
        if file and file.filename.lower().endswith('.png'):
            filename = file.filename
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                file.save(upload_path)
                logging.info(f"File saved at: {upload_path}")
                processed_file = deasterisk_tavern_file(upload_path, app.config['PROCESSED_FOLDER'])
                if not processed_file.startswith("Error"):
                    processed_files.append(processed_file)
                else:
                    logging.error(f"Processing error for {filename}: {processed_file}")
            except Exception as e:
                logging.error(f"Error processing {filename}: {e}")

    if len(processed_files) == 1:
        # If only one file was processed, return it directly
        return redirect(url_for('download_file', filename=os.path.basename(processed_files[0])))
    elif len(processed_files) > 1:
        # If multiple files were processed, create a zip file
        return redirect(url_for('download_zip', filenames=','.join(os.path.basename(f) for f in processed_files)))
    else:
        return "No files were successfully processed."

@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        abort(404)

@app.route('/download_zip')
def download_zip():
    filenames = request.args.get('filenames', '').split(',')
    if not filenames:
        abort(404)

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for filename in filenames:
            file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
            if os.path.exists(file_path):
                zf.write(file_path, filename)
            else:
                logging.warning(f"File not found: {file_path}")

    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name='processed_files.zip'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
