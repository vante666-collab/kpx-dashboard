import qrcode
from qrcode.constants import ERROR_CORRECT_H

URL = "https://sk-es-dashboard-1780105054.netlify.app"
OUT = r"C:\Users\admin.SKENS-T1012-05\Desktop\project\dashboard\dashboard-qr.png"

qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_H, box_size=12, border=4)
qr.add_data(URL)
qr.make(fit=True)
img = qr.make_image(fill_color="#073642", back_color="#fdf6e3").convert("RGB")
img.save(OUT)
print("saved", OUT, img.size)
