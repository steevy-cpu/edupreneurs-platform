import React from 'react';
import { useWindowDimensions, View } from 'react-native';

export type IconName =
  'home' | 'learn' | 'review' | 'profile' | 'check' | 'cross' | 'play' | 'download' | 'chevron' | 'hint' | 'dot' | 'ring' | 'back';

/**
 * Icons drawn with plain Views: no icon font, no SVG library, no image files.
 * That keeps the app small and avoids missing-glyph boxes on old Android fonts.
 * Icons are decorative: the element that contains one carries the accessible label.
 */
export function Icon({ name, color, size: baseSize = 24 }: { name: IconName; color: string; size?: number }) {
  // Icons grow with the phone's text size (up to 1.5x) so they stay in proportion to the words beside them.
  const { fontScale } = useWindowDimensions();
  const size = Math.round(baseSize * Math.min(Math.max(fontScale || 1, 1), 1.5));
  const u = size / 24;
  const box = {
    width: size,
    height: size,
    alignItems: 'center',
    justifyContent: 'center',
  } as const;
  const hidden = {
    accessible: false,
    importantForAccessibility: 'no-hide-descendants',
  } as const;
  const stroke = Math.max(2, Math.round(2.4 * u));

  switch (name) {
    case 'check':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 7 * u,
              height: 13 * u,
              borderRightWidth: stroke,
              borderBottomWidth: stroke,
              borderColor: color,
              transform: [{ rotate: '45deg' }],
              marginTop: -3 * u,
            }}
          />
        </View>
      );
    case 'cross':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              position: 'absolute',
              width: 16 * u,
              height: stroke,
              backgroundColor: color,
              borderRadius: stroke,
              transform: [{ rotate: '45deg' }],
            }}
          />
          <View
            style={{
              position: 'absolute',
              width: 16 * u,
              height: stroke,
              backgroundColor: color,
              borderRadius: stroke,
              transform: [{ rotate: '-45deg' }],
            }}
          />
        </View>
      );
    case 'play':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 0,
              height: 0,
              borderTopWidth: 7 * u,
              borderBottomWidth: 7 * u,
              borderLeftWidth: 11 * u,
              borderTopColor: 'transparent',
              borderBottomColor: 'transparent',
              borderLeftColor: color,
              marginLeft: 3 * u,
            }}
          />
        </View>
      );
    case 'chevron':
    case 'back':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 9 * u,
              height: 9 * u,
              borderTopWidth: stroke,
              borderRightWidth: stroke,
              borderColor: color,
              transform: [{ rotate: name === 'back' ? '-135deg' : '45deg' }],
              marginLeft: name === 'back' ? 4 * u : -4 * u,
            }}
          />
        </View>
      );
    case 'download':
      return (
        <View style={box} {...hidden}>
          <View style={{ width: stroke, height: 9 * u, backgroundColor: color }} />
          <View
            style={{
              width: 8 * u,
              height: 8 * u,
              borderRightWidth: stroke,
              borderBottomWidth: stroke,
              borderColor: color,
              transform: [{ rotate: '45deg' }],
              marginTop: -7 * u,
            }}
          />
          <View
            style={{
              width: 16 * u,
              height: stroke,
              backgroundColor: color,
              borderRadius: stroke,
              marginTop: 4 * u,
            }}
          />
        </View>
      );
    case 'home':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 0,
              height: 0,
              borderLeftWidth: 10 * u,
              borderRightWidth: 10 * u,
              borderBottomWidth: 8 * u,
              borderLeftColor: 'transparent',
              borderRightColor: 'transparent',
              borderBottomColor: color,
            }}
          />
          <View
            style={{
              width: 14 * u,
              height: 9 * u,
              backgroundColor: color,
              borderBottomLeftRadius: 2 * u,
              borderBottomRightRadius: 2 * u,
            }}
          />
        </View>
      );
    case 'learn':
      return (
        <View style={[box, { flexDirection: 'row' }]} {...hidden}>
          <View
            style={{
              width: 9 * u,
              height: 15 * u,
              borderWidth: stroke,
              borderColor: color,
              borderTopLeftRadius: 3 * u,
              borderBottomLeftRadius: 3 * u,
            }}
          />
          <View
            style={{
              width: 9 * u,
              height: 15 * u,
              borderWidth: stroke,
              borderColor: color,
              borderTopRightRadius: 3 * u,
              borderBottomRightRadius: 3 * u,
              marginLeft: -stroke,
            }}
          />
        </View>
      );
    case 'review':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 20 * u,
              height: 20 * u,
              borderRadius: 10 * u,
              borderWidth: stroke,
              borderColor: color,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                width: 8 * u,
                height: 8 * u,
                borderRadius: 4 * u,
                backgroundColor: color,
              }}
            />
          </View>
        </View>
      );
    case 'profile':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 9 * u,
              height: 9 * u,
              borderRadius: 5 * u,
              backgroundColor: color,
            }}
          />
          <View
            style={{
              width: 17 * u,
              height: 8 * u,
              borderTopLeftRadius: 9 * u,
              borderTopRightRadius: 9 * u,
              backgroundColor: color,
              marginTop: 2 * u,
            }}
          />
        </View>
      );
    case 'hint':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 13 * u,
              height: 13 * u,
              borderRadius: 7 * u,
              borderWidth: stroke,
              borderColor: color,
            }}
          />
          <View
            style={{
              width: 7 * u,
              height: 3 * u,
              backgroundColor: color,
              borderRadius: u,
              marginTop: u,
            }}
          />
        </View>
      );
    case 'ring':
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 10 * u,
              height: 10 * u,
              borderRadius: 5 * u,
              borderWidth: stroke,
              borderColor: color,
            }}
          />
        </View>
      );
    case 'dot':
    default:
      return (
        <View style={box} {...hidden}>
          <View
            style={{
              width: 10 * u,
              height: 10 * u,
              borderRadius: 5 * u,
              backgroundColor: color,
            }}
          />
        </View>
      );
  }
}
