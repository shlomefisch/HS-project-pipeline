import { useState } from "react";

/** A product photo from NetSuite. No address, or NetSuite won't show it: a plain sand tile instead, never a broken image. */
export function Photo({ url, size = 44, alt = "" }: { url?: string | null; size?: number; alt?: string }) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size };
  if (!url || failed) return <span className="photo photo-none" style={style} aria-hidden="true" />;
  return <img className="photo" src={url} alt={alt} width={size} height={size} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} style={style} />;
}
