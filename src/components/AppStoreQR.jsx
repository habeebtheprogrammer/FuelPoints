export default function AppStoreQR() {
  const downloadUrl = window.location.origin + "/download";
  const qrCode = `https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=${encodeURIComponent(downloadUrl)}`;

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
        maxWidth: '500px',
        width: '100%',
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
          margin: '0 0 25px 0'
        }}>
          Earn points, get rewards, and save on every visit!
        </p>

        <div style={{
          background: '#f8f9fa',
          borderRadius: '12px',
          padding: '25px',
          display: 'inline-block',
        }}>
          <img 
            src={qrCode} 
            alt="Download Birdies Rewards QR Code"
            style={{
              width: '250px',
              height: '250px',
              display: 'block',
              margin: '0 auto'
            }}
          />
        </div>

        <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'center', gap: '15px', alignItems: 'center' }}>
          <img 
            src="https://developer.apple.com/assets/elements/badges/download-on-the-app-store.svg"
            alt="Download on the App Store"
            style={{ height: '40px' }}
          />
          <img 
            src="https://play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png"
            alt="Get it on Google Play"
            style={{ height: '60px' }}
          />
        </div>

        <div style={{
          marginTop: '20px',
          padding: '15px',
          background: '#1E3A8A',
          borderRadius: '8px',
          color: 'white'
        }}>
          <div style={{ fontSize: '14px', opacity: 0.9, marginBottom: '4px' }}>
            Scan with your phone camera
          </div>
          <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
            Works for iPhone & Android
          </div>
        </div>

        <div className="no-print" style={{ marginTop: '20px', display: 'flex', gap: '12px', justifyContent: 'center' }}>
          <a
            href={qrCode}
            download="birdies-app-qr.png"
            style={{
              background: '#1E3A8A',
              color: 'white',
              padding: '10px 20px',
              borderRadius: '8px',
              textDecoration: 'none',
              fontSize: '14px',
              fontWeight: '600',
            }}
          >
            Download QR
          </a>
          <button
            onClick={handlePrint}
            style={{
              background: '#1E3A8A',
              color: 'white',
              border: 'none',
              padding: '10px 20px',
              fontSize: '14px',
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
