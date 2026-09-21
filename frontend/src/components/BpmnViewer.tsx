import {useEffect, useRef, useState} from 'react'
import NavigatedViewer from 'bpmn-js/lib/NavigatedViewer'
import 'bpmn-js/dist/assets/diagram-js.css'
import 'bpmn-js/dist/assets/bpmn-js.css'
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css'

interface BpmnViewerProps {
    xmlUrl: string
}

function BpmnViewer({xmlUrl}: BpmnViewerProps) {
    const containerRef = useRef<HTMLDivElement>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!containerRef.current) {
            return
        }
        const viewer = new NavigatedViewer({container: containerRef.current})
        let cancelled = false

        fetch(xmlUrl)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`${xmlUrl} failed: ${response.status} ${response.statusText}`)
                }
                return response.text()
            })
            .then((xml) => viewer.importXML(xml))
            .then(() => {
                if (cancelled) {
                    return
                }
                setError(null)
                // @ts-expect-error - bpmn-js's own Canvas type isn't part of the NavigatedViewer typings.
                viewer.get('canvas').zoom('fit-viewport')
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : 'Failed to load diagram')
                }
            })

        return () => {
            cancelled = true
            viewer.destroy()
        }
    }, [xmlUrl])

    return (
        <div className="bpmn-viewer">
            {error && <p className="hint danger">{error}</p>}
            <div className="bpmn-canvas" ref={containerRef}/>
        </div>
    )
}

export default BpmnViewer
