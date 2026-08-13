/**
 * resize.js
 * Resizes images to max 1600px / 90% JPEG quality before upload.
 */

const MAX_PX       = 1600;
const JPEG_QUALITY = 0.90;

function resizeImage(file) {
    return new Promise((resolve) => {
        const img    = new Image();
        const reader = new FileReader();

        reader.onload = e => { img.src = e.target.result; };

        img.onload = () => {
            let w = img.width;
            let h = img.height;

            if (w > MAX_PX || h > MAX_PX) {
                if (w > h) { h = Math.round(h * MAX_PX / w); w = MAX_PX; }
                else       { w = Math.round(w * MAX_PX / h); h = MAX_PX; }
            }

            const canvas = document.createElement('canvas');
            canvas.width  = w;
            canvas.height = h;
            canvas.getContext('2d').drawImage(img, 0, 0, w, h);

            canvas.toBlob(blob => {
                resolve(new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' }));
            }, 'image/jpeg', JPEG_QUALITY);
        };

        reader.readAsDataURL(file);
    });
}

async function resizeFiles(files, maxCount) {
    const limited = Array.from(files).slice(0, maxCount || files.length);
    return Promise.all(limited.map(resizeImage));
}
