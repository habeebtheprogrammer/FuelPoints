import nodemailer from 'nodemailer';

const transporter = nodemailer.createTransport({
  host: 'smtp.office365.com',
  port: 587,
  secure: false,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASSWORD
  }
});

export async function sendWelcomeEmail(email: string, firstName: string, loyaltyId: string): Promise<boolean> {
  if (!email || !process.env.SMTP_USER || !process.env.SMTP_PASSWORD) {
    console.log('Skipping welcome email - missing email address or SMTP credentials');
    return false;
  }

  try {
    await transporter.sendMail({
      from: `"Birdies Rewards" <${process.env.SMTP_USER}>`,
      to: email,
      subject: 'Welcome to Birdies Rewards!',
      html: `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
            <tr>
              <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                  <!-- Header -->
                  <tr>
                    <td style="background-color: #1E3A8A; padding: 30px; text-align: center;">
                      <h1 style="color: #ffffff; margin: 0; font-size: 28px;">Welcome to Birdies Rewards!</h1>
                    </td>
                  </tr>
                  
                  <!-- Content -->
                  <tr>
                    <td style="padding: 40px 30px;">
                      <p style="font-size: 18px; color: #333; margin: 0 0 20px;">Hi ${firstName},</p>
                      
                      <p style="font-size: 16px; color: #555; line-height: 1.6; margin: 0 0 20px;">
                        Thank you for joining the Birdies Rewards program! We're excited to have you as a member.
                      </p>
                      
                      <p style="font-size: 16px; color: #555; line-height: 1.6; margin: 0 0 30px;">
                        Start earning points on every purchase and enjoy exclusive rewards at all Birdies locations.
                      </p>
                      
                      <!-- Loyalty ID Box -->
                      <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F0F4FF; border-radius: 8px; margin-bottom: 30px;">
                        <tr>
                          <td style="padding: 25px; text-align: center;">
                            <p style="font-size: 14px; color: #64748B; margin: 0 0 8px; text-transform: uppercase; letter-spacing: 1px;">Your Loyalty ID</p>
                            <p style="font-size: 24px; color: #1E3A8A; margin: 0; font-weight: bold; font-family: monospace; letter-spacing: 2px;">${loyaltyId}</p>
                          </td>
                        </tr>
                      </table>
                      
                      <!-- How It Works -->
                      <h2 style="font-size: 18px; color: #1E3A8A; margin: 0 0 20px;">How It Works</h2>
                      
                      <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                          <td style="padding: 10px 0;">
                            <table cellpadding="0" cellspacing="0">
                              <tr>
                                <td style="width: 40px; vertical-align: top;">
                                  <div style="width: 30px; height: 30px; background-color: #1E3A8A; border-radius: 50%; text-align: center; line-height: 30px; color: white; font-weight: bold;">1</div>
                                </td>
                                <td style="padding-left: 10px; font-size: 15px; color: #555;">
                                  <strong>Earn 5 points</strong> for every dollar you spend
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding: 10px 0;">
                            <table cellpadding="0" cellspacing="0">
                              <tr>
                                <td style="width: 40px; vertical-align: top;">
                                  <div style="width: 30px; height: 30px; background-color: #1E3A8A; border-radius: 50%; text-align: center; line-height: 30px; color: white; font-weight: bold;">2</div>
                                </td>
                                <td style="padding-left: 10px; font-size: 15px; color: #555;">
                                  <strong>Redeem 100 points</strong> for $1.00 off your purchase
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding: 10px 0;">
                            <table cellpadding="0" cellspacing="0">
                              <tr>
                                <td style="width: 40px; vertical-align: top;">
                                  <div style="width: 30px; height: 30px; background-color: #1E3A8A; border-radius: 50%; text-align: center; line-height: 30px; color: white; font-weight: bold;">3</div>
                                </td>
                                <td style="padding-left: 10px; font-size: 15px; color: #555;">
                                  <strong>Collect punches</strong> on special items for free rewards
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  
                  <!-- Footer -->
                  <tr>
                    <td style="background-color: #F8FAFC; padding: 20px 30px; text-align: center; border-top: 1px solid #E2E8F0;">
                      <p style="font-size: 12px; color: #64748B; margin: 0;">
                        Questions? Reply to this email or visit any Birdies location.
                      </p>
                      <p style="font-size: 12px; color: #94A3B8; margin: 10px 0 0;">
                        &copy; ${new Date().getFullYear()} Birdies Stores. All rights reserved.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
      `
    });
    console.log(`Welcome email sent to ${email}`);
    return true;
  } catch (error) {
    console.error('Failed to send welcome email:', error);
    return false;
  }
}

export async function sendPasswordResetEmail(email: string, firstName: string, resetLink: string): Promise<boolean> {
  if (!email || !process.env.SMTP_USER || !process.env.SMTP_PASSWORD) {
    console.log('Skipping password reset email - missing email address or SMTP credentials');
    return false;
  }

  try {
    await transporter.sendMail({
      from: `"Birdies Rewards" <${process.env.SMTP_USER}>`,
      to: email,
      subject: 'Reset Your Birdies Rewards Password',
      html: `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
            <tr>
              <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                  <tr>
                    <td style="background-color: #1E3A8A; padding: 30px; text-align: center;">
                      <h1 style="color: #ffffff; margin: 0; font-size: 24px;">Reset Your Password</h1>
                    </td>
                  </tr>
                  
                  <tr>
                    <td style="padding: 40px 30px;">
                      <p style="font-size: 18px; color: #333; margin: 0 0 20px;">Hi ${firstName},</p>
                      
                      <p style="font-size: 16px; color: #555; line-height: 1.6; margin: 0 0 20px;">
                        We received a request to reset your Birdies Rewards password. Click the button below to create a new password.
                      </p>
                      
                      <table width="100%" cellpadding="0" cellspacing="0" style="margin: 30px 0;">
                        <tr>
                          <td align="center">
                            <a href="${resetLink}" style="display: inline-block; background-color: #1E3A8A; color: #ffffff; font-size: 16px; font-weight: bold; padding: 15px 40px; text-decoration: none; border-radius: 8px;">
                              Reset Password
                            </a>
                          </td>
                        </tr>
                      </table>
                      
                      <p style="font-size: 14px; color: #888; line-height: 1.6; margin: 0 0 20px;">
                        This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email.
                      </p>
                      
                      <p style="font-size: 12px; color: #aaa; line-height: 1.6; margin: 20px 0 0; padding-top: 20px; border-top: 1px solid #eee;">
                        If the button doesn't work, copy and paste this link into your browser:<br>
                        <a href="${resetLink}" style="color: #1E3A8A; word-break: break-all;">${resetLink}</a>
                      </p>
                    </td>
                  </tr>
                  
                  <tr>
                    <td style="background-color: #F8FAFC; padding: 20px 30px; text-align: center; border-top: 1px solid #E2E8F0;">
                      <p style="font-size: 12px; color: #94A3B8; margin: 0;">
                        &copy; ${new Date().getFullYear()} Birdies Stores. All rights reserved.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
      `
    });
    console.log(`Password reset email sent to ${email}`);
    return true;
  } catch (error) {
    console.error('Failed to send password reset email:', error);
    return false;
  }
}
