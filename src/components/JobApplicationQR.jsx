export default function JobApplicationQR() {
  const applicationUrl = "https://salmanloyalty.replit.app/apply/7-11";
  const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=${encodeURIComponent(applicationUrl)}`;

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
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)'
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          marginBottom: '10px'
        }}>
          <img 
            src="/assets/7-eleven-logo.png" 
            alt="7-Eleven" 
            style={{ height: '60px' }}
            onError={(e) => { e.target.style.display = 'none'; }}
          />
        </div>
        
        <h1 style={{
          color: '#00703c',
          fontSize: '28px',
          margin: '0 0 5px 0',
          fontWeight: 'bold'
        }}>
          WE'RE HIRING!
        </h1>
        
        <p style={{
          color: '#666',
          fontSize: '16px',
          margin: '0 0 25px 0'
        }}>
          Scan to apply online
        </p>

        <div style={{
          background: '#f8f9fa',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '25px'
        }}>
          <img 
            src={qrCodeUrl} 
            alt="QR Code for Job Application"
            style={{
              width: '250px',
              height: '250px',
              display: 'block',
              margin: '0 auto'
            }}
          />
        </div>

        <div style={{
          background: '#00703c',
          color: 'white',
          padding: '15px 20px',
          borderRadius: '8px',
          marginBottom: '20px'
        }}>
          <div style={{ fontSize: '14px', opacity: 0.9, marginBottom: '4px' }}>
            OPENING MARCH 4, 2026
          </div>
          <div style={{ fontSize: '16px', fontWeight: 'bold' }}>
            3599 East-West Hwy
          </div>
          <div style={{ fontSize: '14px' }}>
            Hyattsville, MD 20782
          </div>
        </div>

        <div style={{
          fontSize: '13px',
          color: '#888',
          marginBottom: '20px'
        }}>
          <strong>Positions Available:</strong><br />
          Sales Associate | Food Service | Stock Clerk | Shift Lead
        </div>

        <div className="no-print" style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
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
          <a
            href={qrCodeUrl}
            download="7eleven-hiring-qr.png"
            style={{
              background: '#f0f0f0',
              color: '#333',
              border: 'none',
              padding: '12px 20px',
              fontSize: '16px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              textDecoration: 'none',
              display: 'inline-block'
            }}
          >
            Download QR
          </a>
        </div>
      </div>
    </div>
  );
}
