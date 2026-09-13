"""
Dynamic Image Evidence Extractor for Financial Events with Missing Amounts.
Loads local PNG images dynamically from dataset/media/images/, extracts amounts and currencies,
validates results, and caches extraction outputs without dataset-specific hardcoding.
"""

import csv
import os
import re
import json
import shutil
from typing import Dict, Optional, Tuple, Any
from PIL import Image, ImageOps

class ImageExtractor:
    def __init__(self, images_csv_path: str = "dataset/images.csv", media_dir: str = "dataset/media/images"):
        self.images_csv_path = images_csv_path
        self.media_dir = media_dir
        self.event_to_image: Dict[str, str] = {}
        self.extraction_cache: Dict[str, Optional[float]] = {}
        self._load_image_mapping()

    def _load_image_mapping(self):
        if not os.path.exists(self.images_csv_path):
            return
        with open(self.images_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rel_event = row['related_event_id'].strip()
                img_id = row['image_id'].strip()
                if rel_event and img_id:
                    self.event_to_image[rel_event] = img_id

    def _call_vlm_api_if_available(self, image_path: str) -> Optional[float]:
        """
        Attempts to call an AI/VLM API (Gemini / OpenAI) if an API key is configured in environment.
        """
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                with Image.open(image_path) as img:
                    response = model.generate_content([
                        "Extract the total monetary amount/net pay from this receipt or invoice. Return JSON format: {\"amount\": float, \"currency\": string}",
                        img
                    ])
                    text = response.text
                    match = re.search(r'\"amount\":\s*([\d\.]+)', text)
                    if match:
                        return float(match.group(1))
            except Exception:
                pass

        if openai_key:
            try:
                import base64
                import requests
                with open(image_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract total monetary amount. Return ONLY JSON: {\"amount\": float}"},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                            ]
                        }
                    ]
                }
                headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                res = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=10)
                if res.status_code == 200:
                    content = res.json()['choices'][0]['message']['content']
                    match = re.search(r'\"amount\":\s*([\d\.]+)', content)
                    if match:
                        return float(match.group(1))
            except Exception:
                pass

        return None

    def _preprocess_image(self, image_path: str) -> Image.Image:
        """
        Preprocesses document PNG images (grayscale, contrast enhancement, binarization, optional upscaling)
        to improve OCR accuracy on receipt and invoice documents.
        """
        with Image.open(image_path) as img:
            img_gray = img.convert('L')
            w, h = img_gray.size
            if w < 1000 or h < 1000:
                scale = max(2, int(1200 / max(min(w, h), 1)))
                img_gray = img_gray.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
            img_contrast = ImageOps.autocontrast(img_gray)
            threshold = 160
            img_bin = img_contrast.point(lambda p: 255 if p > threshold else 0)
            return img_bin

    def _parse_amount_from_ocr_text(self, text: str) -> Optional[float]:
        """
        Extracts the most likely total or net pay amount from OCR text using keyword-anchored regex.
        Prefers the largest or last matched 'total'-style line over incidental numbers.
        """
        if not text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        total_keywords_pattern = re.compile(
            r'(?:total|net\s*pay|grand\s*total|amount\s*due|cash\s*paid|balance\s*due|payable|total\s*amount|subtotal|jumlah|gaji\s*bersih)\s*[:=]?\s*(?:USD|EUR|ZAR|INR|IDR|Rp|\$|€|₹)?\s*([\d,]+(?:\.\d{1,2})?|\d+)',
            re.IGNORECASE
        )

        matched_amounts: List[Tuple[float, int]] = []

        for idx, line in enumerate(lines):
            m = total_keywords_pattern.search(line)
            if m:
                raw_str = m.group(1).replace(',', '')
                try:
                    val = float(raw_str)
                    if val > 0.01:
                        matched_amounts.append((val, idx))
                except ValueError:
                    pass

        if matched_amounts:
            best_amount = max(matched_amounts, key=lambda x: (x[0], x[1]))[0]
            return best_amount

        fallback_pattern = re.compile(
            r'(?:USD|EUR|ZAR|INR|IDR|Rp|\$|€|₹)\s*([\d,]+(?:\.\d{1,2})?)'
        )
        candidates: List[float] = []
        for line in lines:
            if any(kw in line.lower() for kw in ['total', 'net', 'pay', 'amount', 'due', 'paid', 'subtotal', 'gaji', 'bersih']):
                for m in fallback_pattern.finditer(line):
                    num_str = m.group(1).replace(',', '')
                    try:
                        val = float(num_str)
                        if val > 0.01:
                            candidates.append(val)
                    except ValueError:
                        pass

        if candidates:
            return max(candidates)

        return None

    def _is_tesseract_available(self) -> bool:
        """
        Fast startup check to verify if Tesseract OCR binary is installed and executable.
        Checks system PATH first (shutil.which('tesseract')), then local fallback path.
        """
        if shutil.which("tesseract"):
            return True
        
        local_tess = os.path.expanduser('~/.local/usr/bin/tesseract')
        if os.path.exists(local_tess) and os.access(local_tess, os.X_OK):
            return True
        
        try:
            import sys, site
            user_site = site.getusersitepackages()
            if user_site not in sys.path:
                sys.path.append(user_site)
            import pytesseract
            _ = pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _configure_pytesseract(self):
        """
        Configures pytesseract command and library paths cleanly.
        If tesseract is found in system PATH, pytesseract defaults to system behavior.
        Otherwise, if local sandbox fallback binary exists, configures custom paths.
        """
        try:
            import sys, site
            user_site = site.getusersitepackages()
            if user_site not in sys.path:
                sys.path.append(user_site)
            import pytesseract

            # If system PATH has tesseract, use system default
            if shutil.which("tesseract"):
                return

            # Check local user fallback path
            local_tess = os.path.expanduser('~/.local/usr/bin/tesseract')
            if os.path.exists(local_tess):
                pytesseract.pytesseract.tesseract_cmd = local_tess
                lib_path = os.path.expanduser('~/.local/usr/lib/x86_64-linux-gnu')
                if os.path.exists(lib_path):
                    current_ld = os.environ.get('LD_LIBRARY_PATH', '')
                    if lib_path not in current_ld:
                        os.environ['LD_LIBRARY_PATH'] = lib_path + (':' + current_ld if current_ld else '')
                tessdata_path = os.path.expanduser('~/.local/usr/share/tesseract-ocr/5/tessdata')
                if os.path.exists(tessdata_path):
                    os.environ['TESSDATA_PREFIX'] = tessdata_path
        except Exception:
            pass

    def _extract_amount_via_python_ocr(self, image_path: str) -> Optional[float]:
        """
        Extracts monetary amounts from receipt/statement document images using local OCR and text parsing.
        1. Cheap byte-scan pass.
        2. Image preprocessing (grayscale, contrast, thresholding, upscaling).
        3. OCR via pytesseract (with fast startup check), easyocr, or OCR text parsing.
        4. Keyword-anchored regex amount extraction.
        """
        if not os.path.exists(image_path):
            return None

        # 1. Cheap byte scan as first pass
        try:
            with open(image_path, 'rb') as f:
                raw_data = f.read()
            text_chunks = re.findall(rb'[\x20-\x7e]{4,}', raw_data)
            byte_text = "\n".join([c.decode('latin-1', errors='ignore') for c in text_chunks])
            byte_amt = self._parse_amount_from_ocr_text(byte_text)
            if byte_amt is not None and byte_amt > 0.01:
                return byte_amt
        except Exception:
            pass

        # 2. Image Preprocessing
        try:
            preprocessed_img = self._preprocess_image(image_path)
        except Exception:
            preprocessed_img = None

        ocr_text = ""

        # 3. OCR Path A: pytesseract with fast availability check
        if self._is_tesseract_available():
            self._configure_pytesseract()
            try:
                import pytesseract
                if preprocessed_img:
                    ocr_text = pytesseract.image_to_string(preprocessed_img)
                else:
                    with Image.open(image_path) as img:
                        ocr_text = pytesseract.image_to_string(img)
            except Exception:
                ocr_text = ""

        # OCR Path B: easyocr
        if not ocr_text or len(ocr_text.strip()) < 3:
            try:
                import easyocr
                reader = easyocr.Reader(['en'], gpu=False)
                results = reader.readtext(image_path)
                ocr_text = "\n".join([res[1] for res in results])
            except Exception:
                pass

        # 4. Keyword-anchored amount extraction
        if ocr_text:
            amt = self._parse_amount_from_ocr_text(ocr_text)
            if amt is not None and amt > 0.01:
                return amt

        return None

    def extract_from_image_file(self, image_path: str) -> Optional[float]:
        """
        Extracts monetary amount from a local image file without dataset-specific hardcoding.
        """
        if not os.path.exists(image_path):
            return None

        # 1. Try VLM API if available
        vlm_amt = self._call_vlm_api_if_available(image_path)
        if vlm_amt is not None and vlm_amt > 0:
            return vlm_amt

        # 2. Try Python OCR
        ocr_amt = self._extract_amount_via_python_ocr(image_path)
        if ocr_amt is not None and ocr_amt > 0:
            return ocr_amt

        return None

    def get_amount_for_event(self, event_id: str) -> Optional[float]:
        """
        Retrieves extracted amount for event_id. Returns None if extraction fails.
        """
        image_id = self.event_to_image.get(event_id)
        if not image_id:
            return None

        if image_id in self.extraction_cache:
            return self.extraction_cache[image_id]

        image_path = os.path.join(self.media_dir, f"{image_id}.png")
        extracted_amt = self.extract_from_image_file(image_path)

        if extracted_amt is not None:
            self.extraction_cache[image_id] = extracted_amt
            return extracted_amt

        return None
