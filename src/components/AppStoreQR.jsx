export default function AppStoreQR() {
  const iosUrl = "https://apps.apple.com/us/app/birdies-rewards/id6757185748";
  const androidUrl = "https://play.google.com/store/apps/details?id=com.birdiesstore&pcampaignid=web_share";
  
  const iosQR = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(iosUrl)}`;
  const androidQR = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(androidUrl)}`;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '20px'
    }}>
      <style>{`
        @media print {
          body { background: white !important; }
          .no-print { display: none !important; }
          .print-container { 
            box-shadow: none !important;
            margin: 0 !important;
          }
        }
      `}</style>
      
      <div className="print-container" style={{
        background: 'white',
        borderRadius: '16px',
        padding: '40px',
        textAlign: 'center',
        maxWidth: '800px',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)'
      }}>
        <img 
          src="/assets/birdies-logo.jpg" 
          alt="Birdies" 
          style={{ height: '60px', marginBottom: '10px' }}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
        
        <h1 style={{
          color: '#1E3A8A',
          fontSize: '28px',
          margin: '0 0 5px 0',
          fontWeight: 'bold'
        }}>
          Download the Birdies Rewards App
        </h1>
        
        <p style={{
          color: '#666',
          fontSize: '16px',
          margin: '0 0 30px 0'
        }}>
          Earn points, get rewards, and save on every visit!
        </p>

        <div style={{
          display: 'flex',
          gap: '40px',
          justifyContent: 'center',
          flexWrap: 'wrap'
        }}>
          <div style={{
            background: '#f8f9fa',
            borderRadius: '12px',
            padding: '20px',
            textAlign: 'center'
          }}>
            <img 
              src="https://developer.apple.com/assets/elements/badges/download-on-the-app-store.svg"
              alt="Download on the App Store"
              style={{ height: '40px', marginBottom: '15px' }}
            />
            <h3 style={{ margin: '0 0 15px 0', color: '#333' }}>iPhone</h3>
            <img 
              src={iosQR} 
              alt="App Store QR Code"
              style={{
                width: '200px',
                height: '200px',
                display: 'block',
                margin: '0 auto 15px'
              }}
            />
            <a
              href={iosQR}
              download="birdies-app-ios-qr.png"
              className="no-print"
              style={{
                background: '#000',
                color: 'white',
                padding: '8px 16px',
                borderRadius: '6px',
                textDecoration: 'none',
                fontSize: '13px',
                display: 'inline-block'
              }}
            >
              Download QR
            </a>
          </div>

          <div style={{
            background: '#f8f9fa',
            borderRadius: '12px',
            padding: '20px',
            textAlign: 'center'
          }}>
            <img 
              src="https://play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png"
              alt="Get it on Google Play"
              style={{ height: '60px', marginBottom: '5px', marginTop: '-10px' }}
            />
            <h3 style={{ margin: '0 0 15px 0', color: '#333' }}>Android</h3>
            <img 
              src={androidQR} 
              alt="Google Play QR Code"
              style={{
                width: '200px',
                height: '200px',
                display: 'block',
                margin: '0 auto 15px'
              }}
            />
            <a
              href={androidQR}
              download="birdies-app-android-qr.png"
              className="no-print"
              style={{
                background: '#01875f',
                color: 'white',
                padding: '8px 16px',
                borderRadius: '6px',
                textDecoration: 'none',
                fontSize: '13px',
                display: 'inline-block'
              }}
            >
              Download QR
            </a>
          </div>
        </div>

        <div style={{
          marginTop: '30px',
          padding: '15px',
          background: '#1E3A8A',
          borderRadius: '8px',
          color: 'white'
        }}>
          <div style={{ fontSize: '14px', opacity: 0.9, marginBottom: '4px' }}>
            Scan with your phone camera to download
          </div>
          <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
            Birdies Rewards
          </div>
        </div>

        <div className="no-print" style={{ marginTop: '25px' }}>
          <button
            onClick={handlePrint}
            style={{
              background: '#1E3A8A',
              color: 'white',
              border: 'none',
              padding: '12px 30px',
              fontSize: '16px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600'
            }}
          >
            Print Flyer
          </button>
        </div>
      </div>
    </div>
  );
}
