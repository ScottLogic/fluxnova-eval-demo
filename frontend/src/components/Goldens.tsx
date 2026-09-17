import {useCallback, useEffect, useState} from 'react'
import useEmblaCarousel from 'embla-carousel-react'
import ReactJson from '@microlink/react-json-view'
import type {Golden} from '../api'

interface GoldenProps {
    goldens: Golden[]
    errors: string | null
}

const JSON_THEME = {
    base00: 'transparent',
    base01: '#2a2f3a',
    base02: '#3a4150',
    base03: '#6b7280',
    base04: '#9ca3af',
    base05: '#e5e7eb',
    base06: '#f3f4f6',
    base07: '#ffffff',
    base08: '#f87171',
    base09: '#fbbf78',
    base0A: '#fbbf24',
    base0B: '#a3e635',
    base0C: '#67e8f9',
    base0D: '#60a5fa',
    base0E: '#c084fc',
    base0F: '#f472b6',
}

function Goldens({goldens, errors}: GoldenProps) {
    const [emblaRef, emblaApi] = useEmblaCarousel({align: 'start', slidesToScroll: 1})
    const [canScrollPrev, setCanScrollPrev] = useState(false)
    const [canScrollNext, setCanScrollNext] = useState(false)

    const onSelect = useCallback(() => {
        if (!emblaApi) return
        setCanScrollPrev(emblaApi.canScrollPrev())
        setCanScrollNext(emblaApi.canScrollNext())
    }, [emblaApi])

    useEffect(() => {
        if (!emblaApi) return
        onSelect()
        emblaApi.on('select', onSelect)
        emblaApi.on('reInit', onSelect)
    }, [emblaApi, onSelect])

    return (
        <section className="panel goldens-panel">
            <div className="panel-head-row">
                <div className="panel-head">
                    <p className="eyebrow">Goldens</p>
                    <h1>Golden scenarios</h1>
                </div>
                {goldens.length > 0 && (
                    <div className="embla-controls">
                        <button
                            type="button"
                            className="btn ghost"
                            onClick={() => emblaApi?.scrollPrev()}
                            disabled={!canScrollPrev}
                            aria-label="Previous golden"
                        >
                            ←
                        </button>
                        <button
                            type="button"
                            className="btn ghost"
                            onClick={() => emblaApi?.scrollNext()}
                            disabled={!canScrollNext}
                            aria-label="Next golden"
                        >
                            →
                        </button>
                    </div>
                )}
            </div>

            {errors && <p className="hint danger">{errors}</p>}
            {!errors && goldens.length === 0 && <p className="hint">Loading goldens…</p>}

            {goldens.length > 0 && (
                <div className="embla" ref={emblaRef}>
                    <div className="embla__container">
                        {goldens.map((golden, index) => (
                            <div className="embla__slide" key={index}>
                                <p className="sample-preview-label">
                                    {(golden.additional_metadata?.scenario as string) ?? `Scenario ${index + 1}`}
                                </p>
                                <ReactJson
                                    src={golden}
                                    name={false}
                                    theme={JSON_THEME}
                                    collapsed={1}
                                    displayDataTypes={false}
                                    displayObjectSize={false}
                                    enableClipboard={false}
                                    style={{background: 'transparent', fontSize: '0.85rem'}}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </section>
    )
}

export default Goldens
