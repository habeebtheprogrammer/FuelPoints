import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  Linking,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { API_BASE_URL } from '../constants/api';

interface StoreLocation {
  id: number;
  locationName: string;
  address1: string;
  address2?: string;
  city: string;
  state: string;
  zipCode: string;
  pdiStoreNumber?: string;
  distance?: number;
}

const coordsCache: { [key: string]: { lat: number; lng: number } } = {};

const getCoords = async (zipCode: string): Promise<{ lat: number; lng: number } | null> => {
  if (coordsCache[zipCode]) {
    return coordsCache[zipCode];
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/geocode/${zipCode}`);
    if (response.ok) {
      const data = await response.json();
      coordsCache[zipCode] = data;
      return data;
    }
  } catch (err) {
    console.log('Geocoding error:', err);
  }
  return null;
};

const getDistance = (lat1: number, lng1: number, lat2: number, lng2: number): number => {
  const R = 3959;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLng/2) * Math.sin(dLng/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

export default function LocationsScreen() {
  const [locations, setLocations] = useState<StoreLocation[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [locationPermission, setLocationPermission] = useState<'granted' | 'denied' | 'undetermined'>('undetermined');
  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    initializeLocation();
  }, []);

  const requestLocationPermission = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      setLocationPermission(status === 'granted' ? 'granted' : 'denied');
      if (status === 'granted') {
        const position = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const coords = { lat: position.coords.latitude, lng: position.coords.longitude };
        setUserCoords(coords);
        return coords;
      }
    } catch (err) {
      console.log('Location error:', err);
      setLocationPermission('denied');
    }
    return null;
  };

  const initializeLocation = async () => {
    const { status } = await Location.getForegroundPermissionsAsync();
    setLocationPermission(status === 'granted' ? 'granted' : status === 'denied' ? 'denied' : 'undetermined');
    
    let coords: { lat: number; lng: number } | null = null;
    
    if (status === 'granted') {
      try {
        const position = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        coords = { lat: position.coords.latitude, lng: position.coords.longitude };
        setUserCoords(coords);
        console.log('Got GPS coords:', coords);
      } catch (err) {
        console.log('Error getting position:', err);
      }
    }
    
    await loadLocations(coords);
  };

  const loadLocations = async (gpsCoords?: { lat: number; lng: number } | null) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/locations`);
      if (response.ok) {
        const data: StoreLocation[] = await response.json();
        
        const sourceCoords = gpsCoords || userCoords;
        
        if (sourceCoords) {
          const withDistance = await Promise.all(data.map(async (loc) => {
            const locCoords = await getCoords(loc.zipCode);
            if (locCoords) {
              return { ...loc, distance: getDistance(sourceCoords.lat, sourceCoords.lng, locCoords.lat, locCoords.lng) };
            }
            return { ...loc, distance: 999 };
          }));
          withDistance.sort((a, b) => (a.distance || 999) - (b.distance || 999));
          setLocations(withDistance);
        } else {
          const customerData = await AsyncStorage.getItem('customer');
          if (customerData) {
            const customer = JSON.parse(customerData);
            if (customer.zipCode) {
              const zipCoords = await getCoords(customer.zipCode);
              if (zipCoords) {
                const withDistance = await Promise.all(data.map(async (loc) => {
                  const locCoords = await getCoords(loc.zipCode);
                  if (locCoords) {
                    return { ...loc, distance: getDistance(zipCoords.lat, zipCoords.lng, locCoords.lat, locCoords.lng) };
                  }
                  return { ...loc, distance: 999 };
                }));
                withDistance.sort((a, b) => (a.distance || 999) - (b.distance || 999));
                setLocations(withDistance);
                return;
              }
            }
          }
          setLocations(data);
        }
      }
    } catch (err) {
      console.log('Error loading locations:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleEnableLocation = async () => {
    const coords = await requestLocationPermission();
    if (coords) {
      setLoading(true);
      await loadLocations(coords);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadLocations();
    setRefreshing(false);
  };

  const openMaps = (location: StoreLocation) => {
    const address = encodeURIComponent(
      `${location.address1}, ${location.city}, ${location.state} ${location.zipCode}`
    );
    const url = Platform.select({
      ios: `maps:0,0?q=${address}`,
      android: `geo:0,0?q=${address}`,
    });
    if (url) {
      Linking.openURL(url);
    }
  };

  const openAllLocationsMap = () => {
    const url = Platform.select({
      ios: `maps:?ll=38.5,-76.8&z=8`,
      android: `geo:38.5,-76.8?z=8`,
    });
    if (url) {
      Linking.openURL(url);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Our Locations</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#1E3A8A" />
        }
        showsVerticalScrollIndicator={false}
      >
        <TouchableOpacity style={styles.heroBanner} onPress={openAllLocationsMap}>
          <Text style={styles.heroIcon}>🗺️</Text>
          <Text style={styles.heroText}>Find a Birdies Near You</Text>
          <Text style={styles.heroSubtext}>
            {locations.length > 0 
              ? `${locations.length} locations • Tap to view on map`
              : 'Loading locations...'}
          </Text>
        </TouchableOpacity>

        {locationPermission !== 'granted' && (
          <TouchableOpacity style={styles.locationBanner} onPress={handleEnableLocation}>
            <View style={styles.locationBannerIcon}>
              <Text style={styles.locationPinIcon}>📍</Text>
            </View>
            <View style={styles.locationBannerText}>
              <Text style={styles.locationBannerTitle}>Enable Location</Text>
              <Text style={styles.locationBannerSubtitle}>
                See stores sorted by distance from you
              </Text>
            </View>
            <Text style={styles.locationBannerArrow}>→</Text>
          </TouchableOpacity>
        )}

        {locationPermission === 'granted' && userCoords && (
          <View style={styles.locationEnabledBanner}>
            <Text style={styles.locationEnabledIcon}>✓</Text>
            <Text style={styles.locationEnabledText}>Showing nearest stores first</Text>
          </View>
        )}

        <Text style={styles.sectionTitle}>ALL LOCATIONS</Text>

        {loading ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>Loading locations...</Text>
          </View>
        ) : locations.length === 0 ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>No locations found</Text>
          </View>
        ) : (
          locations.map((location) => (
            <View key={location.id} style={styles.locationCard}>
              <View style={styles.locationHeader}>
                <View style={styles.storeIcon}>
                  <Text style={styles.storeEmoji}>⛽</Text>
                </View>
                <View style={styles.locationInfo}>
                  <View style={styles.nameRow}>
                    <Text style={styles.locationName}>{location.locationName || `Birdies #${location.pdiStoreNumber || location.id}`}</Text>
                    {location.distance !== undefined && location.distance < 999 && (
                      <Text style={styles.distanceText}>{location.distance.toFixed(1)} mi</Text>
                    )}
                  </View>
                  <Text style={styles.locationAddress}>{location.address1}</Text>
                  {location.address2 && <Text style={styles.locationAddress}>{location.address2}</Text>}
                  <Text style={styles.locationCity}>
                    {location.city}{location.state ? `, ${location.state}` : ''} {location.zipCode}
                  </Text>
                </View>
              </View>
              
              <TouchableOpacity 
                style={styles.directionsBtn}
                onPress={() => openMaps(location)}
              >
                <Text style={styles.directionsIcon}>🧭</Text>
                <Text style={styles.directionsText}>Get Directions</Text>
              </TouchableOpacity>
            </View>
          ))
        )}

        <View style={styles.bottomSpacer} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#FFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
  },
  backBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backIcon: {
    fontSize: 28,
    color: '#1E293B',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1E293B',
  },
  placeholder: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 16,
  },
  heroBanner: {
    backgroundColor: '#1E3A8A',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    marginBottom: 24,
  },
  heroIcon: {
    fontSize: 40,
    marginBottom: 12,
  },
  heroText: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFF',
    marginBottom: 4,
  },
  heroSubtext: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.8)',
  },
  locationBanner: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 2,
    borderColor: '#22C55E',
    borderStyle: 'dashed',
  },
  locationBannerIcon: {
    width: 44,
    height: 44,
    backgroundColor: '#DCFCE7',
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  locationPinIcon: {
    fontSize: 22,
  },
  locationBannerText: {
    flex: 1,
  },
  locationBannerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1E293B',
    marginBottom: 2,
  },
  locationBannerSubtitle: {
    fontSize: 13,
    color: '#64748B',
  },
  locationBannerArrow: {
    fontSize: 20,
    color: '#22C55E',
    fontWeight: '600',
  },
  locationEnabledBanner: {
    backgroundColor: '#DCFCE7',
    borderRadius: 8,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  locationEnabledIcon: {
    fontSize: 16,
    color: '#16A34A',
    marginRight: 8,
    fontWeight: '700',
  },
  locationEnabledText: {
    fontSize: 14,
    color: '#16A34A',
    fontWeight: '600',
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: '#64748B',
    letterSpacing: 0.5,
    marginBottom: 12,
  },
  loadingCard: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 24,
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 14,
    color: '#64748B',
  },
  locationCard: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  locationHeader: {
    flexDirection: 'row',
    marginBottom: 14,
  },
  storeIcon: {
    width: 48,
    height: 48,
    backgroundColor: '#EEF2FF',
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  storeEmoji: {
    fontSize: 24,
  },
  locationInfo: {
    flex: 1,
  },
  nameRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  locationName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1E293B',
    flex: 1,
  },
  distanceText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#22C55E',
    marginLeft: 8,
  },
  locationAddress: {
    fontSize: 14,
    color: '#64748B',
  },
  locationCity: {
    fontSize: 14,
    color: '#64748B',
  },
  directionsBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1E3A8A',
    paddingVertical: 12,
    borderRadius: 8,
  },
  directionsIcon: {
    fontSize: 18,
    marginRight: 8,
  },
  directionsText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFF',
  },
  bottomSpacer: {
    height: 20,
  },
});
