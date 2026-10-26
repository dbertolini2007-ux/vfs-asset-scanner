import io, re, datetime, hmac, hashlib
import streamlit as st
from PIL import Image, ImageOps
from google.oauth2 import service_account
from google.cloud import vision
import gspread
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

st.set_page_config(page_title='VFS Asset Scanner', page_icon='📷', layout='centered')
def require_login():
    """Gate the entire app before loading any operational content."""
    if 'auth' not in st.secrets or 'password_sha256' not in st.secrets['auth']:
        st.error('App password is not configured. Set [auth] password_sha256 in Streamlit secrets.')
        st.stop()
    if st.session_state.get('authenticated'):
        with st.sidebar:
            if st.button('Log out'):
                st.session_state['authenticated'] = False
                st.rerun()
        return
    st.title('🔒 VFS Asset Scanner')
    with st.form('login_form'):
        password = st.text_input('Employee access password', type='password')
        submitted = st.form_submit_button('Sign in', use_container_width=True)
    if submitted:
        entered = hashlib.sha256(password.encode('utf-8')).hexdigest()
        expected = str(st.secrets['auth']['password_sha256']).strip().lower()
        if hmac.compare_digest(entered, expected):
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error('Incorrect password.')
    st.stop()

require_login()
st.title('📷 VFS Asset Scanner')
st.caption('Photograph → Read → Verify → Save')

SCOPES=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/cloud-vision']

def creds():
    return service_account.Credentials.from_service_account_info(dict(st.secrets['google_service_account']),scopes=SCOPES)

def ocr(photo):
    client=vision.ImageAnnotatorClient(credentials=creds())
    result=client.document_text_detection(image=vision.Image(content=photo))
    if result.error.message: raise RuntimeError(result.error.message)
    return result.full_text_annotation.text or ''

def vt_guess(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    for i,line in enumerate(lines):
        if re.search(r'MACHINE\s*#|MACHINE\s*(?:NO|NUMBER)|ASSET\s*(?:#|NO|NUMBER)|\bVT\s*#',line,re.I):
            m=re.search(r'(?<!\d)\d{4,9}(?!\d)',line)
            if m:return m.group()
            if i+1<len(lines):
                m=re.search(r'(?<!\d)\d{4,9}(?!\d)',lines[i+1])
                if m:return m.group()
    candidates=re.findall(r'(?<!\d)\d{5,7}(?!\d)',text)
    return candidates[0] if len(candidates)==1 else ''

def reader_guess(text):
    # Prefer numbers explicitly labeled IMEI, including split lines and spaces.
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        if re.search(r'\\bIMEI\\b', line, re.I):
            sample = ' '.join(lines[i:i+3])
            after = re.split(r'\\bIMEI\\b', sample, maxsplit=1, flags=re.I)[-1]
            for match in re.findall(r'(?<!\\d)(?:\\d[\\s-]*){15}(?!\\d)', after):
                digits = re.sub(r'\\D', '', match)
                if len(digits) == 15:
                    return digits
    for match in re.findall(r'(?<!\\d)(?:\\d[\\s-]*){15}(?!\\d)', text):
        digits = re.sub(r'\\D', '', match)
        if len(digits) == 15:
            return digits
    # Do not silently substitute a serial number for an IMEI.
    return ''

def normalize_photo(data):
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image.thumbnail((2200, 2200))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    out = io.BytesIO()
    image.save(out, format='JPEG', quality=92)
    return out.getvalue()

def extract_on_upload(data, prefix, parser):
    fingerprint = hashlib.sha256(data).hexdigest()
    if st.session_state.get(prefix + '_fingerprint') == fingerprint:
        return
    st.session_state[prefix + '_fingerprint'] = fingerprint
    st.session_state[prefix + '_value'] = ''
    st.session_state[prefix + '_verified'] = False
    st.session_state[prefix + '_ocr_raw'] = ''
    st.session_state[prefix + '_error'] = ''
    try:
        with st.spinner('Reading photo automatically…'):
            raw = ocr(data)
            st.session_state[prefix + '_ocr_raw'] = raw
            st.session_state[prefix + '_value'] = parser(raw)
            if not raw.strip():
                st.session_state[prefix + '_error'] = 'OCR detected no text. Retake a close, well-lit photo.'
            elif not st.session_state[prefix + '_value']:
                st.session_state[prefix + '_error'] = 'Text detected but no matching number. Review OCR text below or enter the number.'
    except Exception as exc:
        st.session_state[prefix + '_error'] = 'OCR service error: ' + str(exc)

def upload_photo(drive, folder_id, name, content):
    metadata={'name':name,'parents':[folder_id]}
    media=MediaIoBaseUpload(io.BytesIO(content),mimetype='image/jpeg',resumable=False)
    obj=drive.files().create(body=metadata,media_body=media,fields='id,webViewLink',supportsAllDrives=True).execute()
    return obj.get('webViewLink') or 'https://drive.google.com/file/d/'+obj['id']+'/view'

def save_record(employee, vt, reader, kind, vt_bytes, reader_bytes):
    c=creds()
    sheet_id=st.secrets['app']['spreadsheet_id']
    folder_id=st.secrets['app']['drive_folder_id']
    gc=gspread.authorize(c)
    ws=gc.open_by_key(sheet_id).sheet1
    headers=['Timestamp (UTC)','Employee','VT Asset Number','Reader Identifier','Reader ID Type','VT Photo','Reader Photo']
    if not ws.row_values(1):ws.append_row(headers)
    existing=ws.col_values(3)[1:]
    if vt in existing:raise ValueError('This VT number already exists in the sheet. Please review the existing record before saving.')
    drive=build('drive','v3',credentials=c,cache_discovery=False)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    vt_link=upload_photo(drive,folder_id,f'{vt}_{stamp}_VT.jpg',vt_bytes)
    reader_link=upload_photo(drive,folder_id,f'{vt}_{stamp}_READER.jpg',reader_bytes)
    ws.append_row([datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),employee,vt,reader,kind,vt_link,reader_link],value_input_option='RAW')

if 'last_vt' not in st.session_state:st.session_state.last_vt=''
if 'last_reader' not in st.session_state:st.session_state.last_reader=''

employee=st.text_input('Employee name',placeholder='First and last name')

st.subheader('1. VT machine tag')
vt_source=st.radio('VT photo source',['Take photo','Upload photo'],horizontal=True,key='vtsrc')
vt_file=st.camera_input('Photograph VT tag',key='vtcam') if vt_source=='Take photo' else st.file_uploader('Upload VT tag photo',type=['jpg','jpeg','png'],key='vtup')
vt_bytes=None
if vt_file:
    vt_bytes = normalize_photo(vt_file.getvalue())
    st.image(vt_bytes, caption='VT label', width=280)
    extract_on_upload(vt_bytes, 'vt', vt_guess)
    if st.session_state.get('vt_error'):
        st.warning(st.session_state['vt_error'])
    elif st.session_state.get('vt_value'):
        st.success('VT number extracted. Verify against the machine.')
vt=st.text_input('Extracted VT number — correct if needed',key='vt_value')
vt_verified=st.checkbox('I checked this VT number against the machine tag',key='vt_verified')

st.subheader('2. Credit card reader label')
st.caption('Capture the IMEI label when available. Some ePort units show a reader serial number instead.')
reader_source=st.radio('Reader photo source',['Take photo','Upload photo'],horizontal=True,key='rdsrc')
reader_file=st.camera_input('Photograph reader label',key='rdcam') if reader_source=='Take photo' else st.file_uploader('Upload reader label photo',type=['jpg','jpeg','png'],key='rdup')
reader_bytes=None
if reader_file:
    reader_bytes = normalize_photo(reader_file.getvalue())
    st.image(reader_bytes, caption='Reader label', width=280)
    extract_on_upload(reader_bytes, 'reader', reader_guess)
    if st.session_state.get('reader_error'):
        st.warning(st.session_state['reader_error'])
    elif st.session_state.get('reader_value'):
        st.success('IMEI extracted. Verify against the reader.')
reader=st.text_input('Extracted reader number — correct if needed',key='reader_value')
kind=st.selectbox('Reader identifier type',['IMEI (15 digits)','Serial number / other ID'])
reader_verified=st.checkbox('I checked this number against the reader label',key='reader_verified')

valid=bool(employee.strip() and vt_bytes and reader_bytes and vt.strip() and reader.strip() and vt_verified and reader_verified)
if kind=='IMEI (15 digits)' and reader and not re.fullmatch(r'\d{15}',reader.strip()):
    st.warning('An IMEI must be exactly 15 digits. If this is a printed serial number, choose “Serial number / other ID”.')
    valid=False
if st.button('✅ Submit verified asset',type='primary',use_container_width=True,disabled=not valid):
    try:
        with st.spinner('Saving photos and spreadsheet record…'):
            save_record(employee.strip(),vt.strip(),reader.strip(),kind,vt_bytes,reader_bytes)
        st.success('Asset saved to Google Sheets and photos saved to Google Drive.')
        st.balloons()
    except KeyError:
        st.error('Google credentials or sheet/folder IDs are not configured. See README.md.')
    except Exception as e:st.error(f'Save failed: {e}')

with st.expander('OCR troubleshooting'):
    st.caption('If the extracted number is incorrect, correct it before verifying. Recognition is not guaranteed, particularly for handwriting.')
    if st.session_state.get('vt_error'):st.error(st.session_state['vt_error'])
    if st.session_state.get('vt_ocr_raw'):st.code(st.session_state['vt_ocr_raw'])
    if st.session_state.get('reader_error'):st.error(st.session_state['reader_error'])
    if st.session_state.get('reader_ocr_raw'):st.code(st.session_state['reader_ocr_raw'])
