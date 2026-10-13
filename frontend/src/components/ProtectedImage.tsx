import { useEffect, useRef, useState, type ImgHTMLAttributes } from 'react'
import { authFetch } from '../auth-client'

type Props = ImgHTMLAttributes<HTMLImageElement> & { onUnavailable: () => void }

export default function ProtectedImage({ src, onUnavailable, ...props }: Props) {
  const [url, setUrl] = useState<string>()
  const errorHandler = useRef(onUnavailable)
  errorHandler.current = onUnavailable
  useEffect(() => {
    let active = true
    let objectUrl: string | undefined
    const controller = new AbortController()
    setUrl(undefined)
    if (src) void authFetch(src, { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error('Image unavailable')
      const blob = await response.blob()
      if (!active) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    }).catch(() => {
      if (active) errorHandler.current()
    })
    return () => { active = false; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [src])
  return <img {...props} src={url} onError={() => errorHandler.current()} />
}
