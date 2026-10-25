import {useEffect, useRef, useState} from 'react'
import NavigatedViewer from 'bpmn-js/lib/NavigatedViewer'
import 'bpmn-js/dist/assets/diagram-js.css'
import 'bpmn-js/dist/assets/bpmn-js.css'
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css'

const ACTIVE_MARKER = 'bpmn-activity-active'
const DONE_MARKER = 'bpmn-activity-done'

// bpmn-js's own Canvas type isn't part of the NavigatedViewer typings — `.get`
// returns `unknown`, so this narrows it to just the marker methods this
// component actually calls.
interface BpmnCanvas {
    addMarker(elementId: string, className: string): void
    removeMarker(elementId: string, className: string): void
}

interface BpmnViewerProps {
    xmlUrl: string
    // BPMN element ids to highlight as currently running / already finished.
    // Optional — a caller showing the diagram purely for reference (no live
    // run to track) just omits these.
    activeElementIds?: string[]
    doneElementIds?: string[]
}

function BpmnViewer({xmlUrl, activeElementIds = [], doneElementIds = []}: BpmnViewerProps) {
    const containerRef = useRef<HTMLDivElement>(null)
    const viewerRef = useRef<NavigatedViewer | null>(null)
    const markedElementIdsRef = useRef<string[]>([])
    const [error, setError] = useState<string | null>(null)
    const [diagramReady, setDiagramReady] = useState(false)

    // Loads the diagram once per xmlUrl — deliberately not re-run when the
    // highlight props change, so polling for live progress doesn't re-fetch/
    // re-import the XML (which would flicker and reset pan/zoom) on every tick.
    useEffect(() => {
        if (!containerRef.current) {
            return
        }
        const viewer = new NavigatedViewer({container: containerRef.current})
        viewerRef.current = viewer
        let cancelled = false
        setDiagramReady(false)

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
                markedElementIdsRef.current = []
                setDiagramReady(true)
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : 'Failed to load diagram')
                }
            })

        return () => {
            cancelled = true
            viewer.destroy()
            viewerRef.current = null
        }
    }, [xmlUrl])

    // Re-applies highlight markers whenever the active/done element ids change
    // (e.g. each poll tick), without touching the loaded diagram itself.
    useEffect(() => {
        const viewer = viewerRef.current
        if (!diagramReady || !viewer) {
            return
        }
        const canvas = viewer.get('canvas') as BpmnCanvas

        for (const elementId of markedElementIdsRef.current) {
            try {
                canvas.removeMarker(elementId, ACTIVE_MARKER)
                canvas.removeMarker(elementId, DONE_MARKER)
            } catch {
                // Element no longer exists on this diagram — nothing to clear.
            }
        }

        const nextMarked: string[] = []
        for (const elementId of doneElementIds) {
            try {
                canvas.addMarker(elementId, DONE_MARKER)
                nextMarked.push(elementId)
            } catch {
                // Id doesn't match an element on this diagram — ignore.
            }
        }
        for (const elementId of activeElementIds) {
            try {
                canvas.addMarker(elementId, ACTIVE_MARKER)
                nextMarked.push(elementId)
            } catch {
                // Id doesn't match an element on this diagram — ignore.
            }
        }
        markedElementIdsRef.current = nextMarked
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [diagramReady, activeElementIds.join(','), doneElementIds.join(',')])

    return (
        <div className="bpmn-viewer">
            {error && <p className="hint danger">{error}</p>}
            <div className="bpmn-canvas" ref={containerRef}/>
        </div>
    )
}

export default BpmnViewer
