import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** QR строится в браузере (библиотека в бандле, без внешних сервисов) и рисуется SVG. */
export function QrCode({ value, label, size = 184 }: { value: string; label: string; size?: number }) {
  const path = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    const count = qr.getModuleCount();
    let d = "";
    for (let row = 0; row < count; row += 1)
      for (let col = 0; col < count; col += 1) if (qr.isDark(row, col)) d += `M${col + 2} ${row + 2}h1v1h-1z`;
    return { d, box: count + 4 };
  }, [value]);

  return (
    <svg
      className="qr"
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${path.box} ${path.box}`}
      shapeRendering="crispEdges"
    >
      <rect width={path.box} height={path.box} fill="#fff" />
      <path d={path.d} fill="#000" />
    </svg>
  );
}
