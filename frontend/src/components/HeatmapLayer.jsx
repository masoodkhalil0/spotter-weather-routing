import L from 'leaflet'
import { memo, useMemo } from 'react'
import { CircleMarker, Pane } from 'react-leaflet'
import { RISK_LEVELS } from '../utils/risk'

const HEATMAP_BASE_RADIUS = 10
const HEATMAP_RADIUS_STEP = 3
const HEATMAP_BASE_OPACITY = 0.35
const HEATMAP_OPACITY_STEP = 0.1

const HeatmapLayer = memo(function HeatmapLayer({ heatmap, selectedHour }) {
  const renderer = useMemo(() => L.canvas({ pane: 'heatmap' }), [])
  const hour = Math.min(selectedHour, Math.max((heatmap?.hours ?? 1) - 1, 0))

  const markerConfigs = useMemo(() => {
    if (!heatmap?.points?.length) {
      return []
    }

    return heatmap.points.flatMap((point, index) => {
      const level = point.levels?.[hour]

      if (level == null) {
        return []
      }

      const risk = RISK_LEVELS[level - 1]

      if (!risk) {
        return []
      }

      return [
        {
          key: index,
          center: [point.lat, point.lon],
          radius: HEATMAP_BASE_RADIUS + HEATMAP_RADIUS_STEP * (level - 1),
          pathOptions: {
            color: risk.color,
            fillColor: risk.color,
            fillOpacity: HEATMAP_BASE_OPACITY + HEATMAP_OPACITY_STEP * (level - 1),
            weight: 0,
          },
        },
      ]
    })
  }, [heatmap, hour])

  return (
    <Pane name="heatmap" style={{ zIndex: 350 }}>
      {markerConfigs.map((markerConfig) => (
        <CircleMarker
          key={markerConfig.key}
          center={markerConfig.center}
          radius={markerConfig.radius}
          pathOptions={markerConfig.pathOptions}
          renderer={renderer}
          interactive={false}
        />
      ))}
    </Pane>
  )
})

export default HeatmapLayer