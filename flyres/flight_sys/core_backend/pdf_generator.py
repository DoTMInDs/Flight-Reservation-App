# core/utils/pdf_generator.py
import io
import os
from datetime import datetime
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
import logging

logger = logging.getLogger(__name__)

class PDFGenerator:
    """Base PDF generator class with common functionality"""
    
    @staticmethod
    def format_currency(amount, currency='USD'):
        """Format currency for display"""
        if not amount:
            return 'N/A'
        try:
            amount = float(amount)
            return f"${amount:,.2f}" if currency == 'USD' else f"{currency} {amount:,.2f}"
        except:
            return str(amount)
    
    @staticmethod
    def format_duration(iso_duration):
        """Format ISO 8601 duration"""
        if not iso_duration:
            return 'N/A'
        
        duration = str(iso_duration).replace('PT', '')
        hours = ''
        minutes = ''
        
        if 'H' in duration:
            parts = duration.split('H')
            hours = f"{parts[0]}h "
            duration = parts[1] if len(parts) > 1 else ""
        
        if 'M' in duration:
            parts = duration.split('M')
            minutes = f"{parts[0]}m"
        
        return f"{hours}{minutes}".strip()
    
    @staticmethod
    def format_datetime(dt_string):
        """Format datetime string"""
        if not dt_string:
            return 'N/A'
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y %I:%M %p')
        except:
            return dt_string

class ReportLabPDFGenerator(PDFGenerator):
    """PDF generator using ReportLab"""
    
    @staticmethod
    def generate_itinerary(booking, flight_details, passengers, filename=None):
        """
        Generate PDF itinerary using ReportLab
        
        Args:
            booking: Reservation object
            flight_details: Flight details dictionary
            passengers: List of passenger dictionaries
            filename: Output filename
        
        Returns:
            BytesIO object with PDF content
        """
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch, cm
            from reportlab.lib import colors
            from reportlab.pdfgen import canvas
            from reportlab.graphics.barcode import code128
            from reportlab.graphics.shapes import Drawing
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            
            # Create buffer
            buffer = io.BytesIO()
            
            # Setup document
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72
            )
            
            # Styles
            styles = getSampleStyleSheet()
            
            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1E40AF'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=16,
                textColor=colors.HexColor('#1E3A8A'),
                spaceAfter=12,
                spaceBefore=20
            )
            
            subheading_style = ParagraphStyle(
                'CustomSubheading',
                parent=styles['Heading3'],
                fontSize=14,
                textColor=colors.HexColor('#374151'),
                spaceAfter=8,
                spaceBefore=15
            )
            
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontSize=11,
                textColor=colors.HexColor('#4B5563')
            )
            
            bold_style = ParagraphStyle(
                'CustomBold',
                parent=styles['Normal'],
                fontSize=11,
                textColor=colors.HexColor('#1F2937'),
                fontName='Helvetica-Bold'
            )
            
            small_style = ParagraphStyle(
                'CustomSmall',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#6B7280')
            )
            
            # Build story
            story = []
            
            # Header
            story.append(Paragraph("FLIGHT ITINERARY", title_style))
            story.append(Spacer(1, 10))
            
            # Booking Info Section
            story.append(Paragraph("Booking Information", heading_style))
            
            booking_info = [
                ["Booking Reference:", booking.airline_pnr],
                ["Booking Date:", booking.created_at.strftime('%b %d, %Y %I:%M %p')],
                ["Status:", booking.status],
                ["Total Price:", PDFGenerator.format_currency(booking.total_price)],
                ["Contact Email:", booking.contact_email],
                ["Expires:", booking.expires_at.strftime('%b %d, %Y %I:%M %p') if booking.expires_at else 'N/A'],
            ]
            
            booking_table = Table(booking_info, colWidths=[2*inch, 3*inch])
            booking_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#4B5563')),
                ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#1F2937')),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(booking_table)
            story.append(Spacer(1, 20))
            
            # Flight Details Section
            if flight_details:
                story.append(Paragraph("Flight Details", heading_style))
                
                # Route header
                route_text = f"{flight_details.get('origin', 'N/A')} → {flight_details.get('destination', 'N/A')}"
                story.append(Paragraph(route_text, subheading_style))
                
                # Airline and flight number
                airline_info = f"{flight_details.get('airline_name', '')} • Flight {flight_details.get('flight_number', '')}"
                story.append(Paragraph(airline_info, normal_style))
                story.append(Spacer(1, 10))
                
                # Flight timeline
                flight_data = [
                    [
                        Paragraph("<b>Departure</b><br/>" + 
                                 (PDFGenerator.format_datetime(flight_details.get('departure')) if flight_details.get('departure') else 'N/A'),
                                 normal_style),
                        "",
                        Paragraph("<b>Arrival</b><br/>" +
                                 (PDFGenerator.format_datetime(flight_details.get('arrival')) if flight_details.get('arrival') else 'N/A'),
                                 normal_style)
                    ],
                    [
                        Paragraph(f"<b>{flight_details.get('origin', 'N/A')}</b>", normal_style),
                        Paragraph(f"Duration: {PDFGenerator.format_duration(flight_details.get('duration'))}<br/>" +
                                 f"Stops: {flight_details.get('stops', 0)}", 
                                 small_style),
                        Paragraph(f"<b>{flight_details.get('destination', 'N/A')}</b>", normal_style)
                    ]
                ]
                
                flight_table = Table(flight_data, colWidths=[2.5*inch, 2*inch, 2.5*inch])
                flight_table.setStyle(TableStyle([
                    ('GRID', (1, 0), (1, -1), 0.5, colors.grey),
                    ('LINEABOVE', (1, 0), (1, -1), 0.5, colors.grey),
                    ('LINEBELOW', (1, 0), (1, -1), 0.5, colors.grey),
                    ('ALIGN', (1, 0), (1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ]))
                story.append(flight_table)
                story.append(Spacer(1, 20))
            
            # Passenger Details Section
            if passengers:
                story.append(Paragraph("Passenger Details", heading_style))
                
                passenger_data = [["No.", "Name", "Date of Birth", "Gender", "Email", "Document"]]
                
                for i, passenger in enumerate(passengers, 1):
                    name = f"{passenger.get('name', {}).get('firstName', '')} {passenger.get('name', {}).get('lastName', '')}"
                    dob = passenger.get('dateOfBirth', 'N/A')
                    gender = passenger.get('gender', 'N/A')
                    email = passenger.get('contact', {}).get('emailAddress', 'N/A')
                    
                    # Get document info
                    doc_info = 'N/A'
                    if passenger.get('documents') and len(passenger['documents']) > 0:
                        doc = passenger['documents'][0]
                        doc_info = f"{doc.get('documentType', '')}: {doc.get('number', '')[:8]}..."
                    
                    passenger_data.append([
                        str(i),
                        Paragraph(name, normal_style),
                        Paragraph(dob[:10] if dob else 'N/A', normal_style),
                        Paragraph(gender, normal_style),
                        Paragraph(email, normal_style),
                        Paragraph(doc_info, normal_style)
                    ])
                
                passenger_table = Table(passenger_data, colWidths=[0.5*inch, 2*inch, inch, 0.8*inch, 2*inch, 1.5*inch])
                passenger_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3B82F6')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Center numbers
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(passenger_table)
                story.append(Spacer(1, 20))
            
            # Footer
            story.append(Spacer(1, 30))
            story.append(Paragraph("Important Information", subheading_style))
            
            notes = [
                "1. Please arrive at the airport at least 2 hours before departure for domestic flights and 3 hours for international flights.",
                "2. Bring valid identification (passport for international flights, government-issued ID for domestic).",
                "3. Check baggage allowance with the airline before packing.",
                "4. Online check-in is available 24-48 hours before departure.",
                "5. For changes or cancellations, contact our customer service or visit our website.",
                "6. Keep this itinerary with you during your journey."
            ]
            
            for note in notes:
                story.append(Paragraph(f"• {note}", small_style))
                story.append(Spacer(1, 3))
            
            story.append(Spacer(1, 20))
            story.append(Paragraph("Thank you for choosing FlightReserve!", normal_style))
            story.append(Paragraph("For assistance: support@flightreserve.com | +1-800-FLY-RESERVE", small_style))
            
            # Generate Barcode
            if booking.airline_pnr:
                story.append(Spacer(1, 20))
                barcode_drawing = Drawing(100, 50)
                barcode = code128.Code128(booking.airline_pnr, barHeight=30, barWidth=0.5)
                barcode_drawing.add(barcode)
                story.append(barcode_drawing)
                story.append(Paragraph(f"Reference: {booking.airline_pnr}", small_style))
            
            # Build PDF
            doc.build(story)
            
            # Get PDF content
            pdf = buffer.getvalue()
            buffer.close()
            
            return io.BytesIO(pdf)
            
        except ImportError as e:
            logger.error(f"ReportLab not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Error generating ReportLab PDF: {e}")
            raise

class WeasyPrintPDFGenerator(PDFGenerator):
    """PDF generator using WeasyPrint"""
    
    @staticmethod
    def generate_itinerary(booking, flight_details, passengers, filename=None):
        """
        Generate PDF itinerary using WeasyPrint
        
        Args:
            booking: Reservation object
            flight_details: Flight details dictionary
            passengers: List of passenger dictionaries
            filename: Output filename
        
        Returns:
            BytesIO object with PDF content
        """
        try:
            from weasyprint import HTML
            from weasyprint.text.fonts import FontConfiguration
            import tempfile
            import base64
            
            # Create HTML template
            html_content = WeasyPrintPDFGenerator._create_html_template(
                booking, flight_details, passengers
            )
            
            # Create font configuration
            font_config = FontConfiguration()
            
            # Generate PDF
            html = HTML(string=html_content)
            
            # Create buffer
            buffer = io.BytesIO()
            
            # Write PDF to buffer
            html.write_pdf(buffer, font_config=font_config)
            
            # Reset buffer position
            buffer.seek(0)
            
            return buffer
            
        except ImportError as e:
            logger.error(f"WeasyPrint not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Error generating WeasyPrint PDF: {e}")
            raise
    
    @staticmethod
    def _create_html_template(booking, flight_details, passengers):
        """Create HTML template for WeasyPrint"""
        
        # Helper functions for template
        def format_currency(amount):
            if not amount:
                return 'N/A'
            try:
                amount = float(amount)
                return f"${amount:,.2f}"
            except:
                return str(amount)
        
        def format_datetime(dt_string):
            if not dt_string:
                return 'N/A'
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
                return dt.strftime('%b %d, %Y %I:%M %p')
            except:
                return dt_string
        
        # Generate passenger table rows
        passenger_rows = ""
        for i, passenger in enumerate(passengers, 1):
            name = f"{passenger.get('name', {}).get('firstName', '')} {passenger.get('name', {}).get('lastName', '')}"
            dob = passenger.get('dateOfBirth', 'N/A')
            gender = passenger.get('gender', 'N/A')
            email = passenger.get('contact', {}).get('emailAddress', 'N/A')
            
            # Get document info
            doc_info = 'N/A'
            if passenger.get('documents') and len(passenger['documents']) > 0:
                doc = passenger['documents'][0]
                doc_info = f"{doc.get('documentType', '')}: {doc.get('number', '')[:8]}..."
            
            passenger_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{name}</td>
                <td>{dob[:10] if dob else 'N/A'}</td>
                <td>{gender}</td>
                <td>{email}</td>
                <td>{doc_info}</td>
            </tr>
            """
        
        # Flight details section
        flight_section = ""
        if flight_details:
            flight_section = f"""
            <div class="section">
                <h2>Flight Details</h2>
                <div class="flight-card">
                    <div class="flight-header">
                        <h3>{flight_details.get('origin', 'N/A')} → {flight_details.get('destination', 'N/A')}</h3>
                        <p class="airline">{flight_details.get('airline_name', '')} • Flight {flight_details.get('flight_number', '')}</p>
                    </div>
                    <div class="flight-timeline">
                        <div class="departure">
                            <p class="label">Departure</p>
                            <p class="time">{format_datetime(flight_details.get('departure'))}</p>
                            <p class="airport">{flight_details.get('origin', 'N/A')}</p>
                        </div>
                        <div class="duration">
                            <div class="line"></div>
                            <div class="plane">✈</div>
                            <p>Duration: {PDFGenerator.format_duration(flight_details.get('duration'))}</p>
                            <p>Stops: {flight_details.get('stops', 0)}</p>
                        </div>
                        <div class="arrival">
                            <p class="label">Arrival</p>
                            <p class="time">{format_datetime(flight_details.get('arrival'))}</p>
                            <p class="airport">{flight_details.get('destination', 'N/A')}</p>
                        </div>
                    </div>
                </div>
            </div>
            """
        
        # HTML template
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Flight Itinerary - {booking.airline_pnr}</title>
            <style>
                @page {{
                    size: letter;
                    margin: 2cm;
                }}
                
                body {{
                    font-family: 'Helvetica', 'Arial', sans-serif;
                    color: #333;
                    line-height: 1.6;
                }}
                
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                    border-bottom: 3px solid #1E40AF;
                    padding-bottom: 20px;
                }}
                
                .title {{
                    color: #1E40AF;
                    font-size: 28px;
                    font-weight: bold;
                    margin-bottom: 10px;
                }}
                
                .section {{
                    margin-bottom: 25px;
                    page-break-inside: avoid;
                }}
                
                h2 {{
                    color: #1E3A8A;
                    font-size: 20px;
                    border-bottom: 2px solid #E5E7EB;
                    padding-bottom: 8px;
                    margin-bottom: 15px;
                }}
                
                h3 {{
                    color: #374151;
                    font-size: 16px;
                    margin-bottom: 5px;
                }}
                
                .info-grid {{
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 15px;
                    margin-bottom: 20px;
                }}
                
                .info-item {{
                    display: flex;
                    justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid #F3F4F6;
                }}
                
                .info-label {{
                    color: #4B5563;
                    font-weight: 500;
                }}
                
                .info-value {{
                    color: #1F2937;
                    font-weight: bold;
                }}
                
                .flight-card {{
                    border: 1px solid #E5E7EB;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 15px 0;
                    background: #F9FAFB;
                }}
                
                .flight-header {{
                    text-align: center;
                    margin-bottom: 20px;
                }}
                
                .flight-timeline {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    text-align: center;
                }}
                
                .departure, .arrival {{
                    flex: 1;
                }}
                
                .duration {{
                    flex: 2;
                    position: relative;
                    padding: 0 20px;
                }}
                
                .line {{
                    position: absolute;
                    top: 50%;
                    left: 0;
                    right: 0;
                    height: 2px;
                    background: #D1D5DB;
                    z-index: 1;
                }}
                
                .plane {{
                    position: relative;
                    z-index: 2;
                    font-size: 20px;
                    background: white;
                    padding: 0 10px;
                }}
                
                .label {{
                    color: #6B7280;
                    font-size: 12px;
                    text-transform: uppercase;
                    margin-bottom: 5px;
                }}
                
                .time {{
                    color: #1F2937;
                    font-size: 18px;
                    font-weight: bold;
                    margin-bottom: 5px;
                }}
                
                .airport {{
                    color: #374151;
                    font-size: 14px;
                    font-weight: 500;
                }}
                
                .airline {{
                    color: #6B7280;
                    font-size: 14px;
                }}
                
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 15px 0;
                }}
                
                th {{
                    background-color: #3B82F6;
                    color: white;
                    text-align: left;
                    padding: 10px;
                    font-weight: bold;
                }}
                
                td {{
                    border: 1px solid #E5E7EB;
                    padding: 8px;
                    vertical-align: middle;
                }}
                
                tr:nth-child(even) {{
                    background-color: #F9FAFB;
                }}
                
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 2px solid #E5E7EB;
                    color: #6B7280;
                    font-size: 12px;
                }}
                
                .notes {{
                    background-color: #FEF3C7;
                    border-left: 4px solid #F59E0B;
                    padding: 15px;
                    margin: 20px 0;
                }}
                
                .barcode {{
                    text-align: center;
                    margin: 20px 0;
                    font-family: 'Code128', monospace;
                    font-size: 24px;
                    letter-spacing: 2px;
                }}
                
                @media print {{
                    .no-print {{
                        display: none;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1 class="title">FLIGHT ITINERARY</h1>
                <p>Generated on: {datetime.now().strftime('%B %d, %Y %I:%M %p')}</p>
            </div>
            
            <div class="section">
                <h2>Booking Information</h2>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">Booking Reference:</span>
                        <span class="info-value">{booking.airline_pnr}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Booking Date:</span>
                        <span class="info-value">{booking.created_at.strftime('%b %d, %Y %I:%M %p')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Status:</span>
                        <span class="info-value">{booking.status}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Total Price:</span>
                        <span class="info-value">{format_currency(booking.total_price)}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Contact Email:</span>
                        <span class="info-value">{booking.contact_email}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Expires:</span>
                        <span class="info-value">{booking.expires_at.strftime('%b %d, %Y %I:%M %p') if booking.expires_at else 'N/A'}</span>
                    </div>
                </div>
            </div>
            
            {flight_section}
            
            <div class="section">
                <h2>Passenger Details</h2>
                <table>
                    <thead>
                        <tr>
                            <th>No.</th>
                            <th>Name</th>
                            <th>Date of Birth</th>
                            <th>Gender</th>
                            <th>Email</th>
                            <th>Document</th>
                        </tr>
                    </thead>
                    <tbody>
                        {passenger_rows}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>Important Information</h2>
                <div class="notes">
                    <p><strong>Please note:</strong></p>
                    <ul style="margin: 10px 0; padding-left: 20px;">
                        <li>Arrive at the airport at least 2 hours before departure (3 hours for international)</li>
                        <li>Bring valid identification (passport for international flights)</li>
                        <li>Check baggage allowance with the airline</li>
                        <li>Online check-in available 24-48 hours before departure</li>
                        <li>Keep this itinerary with you during your journey</li>
                    </ul>
                </div>
            </div>
            
            <div class="footer">
                <p>Thank you for choosing FlightReserve!</p>
                <p>For assistance: support@flightreserve.com | +1-800-FLY-RESERVE</p>
                <div class="barcode">
                    *{booking.airline_pnr}*
                    <br>
                    <small>Reference: {booking.airline_pnr}</small>
                </div>
                <p style="text-align: center; font-size: 10px; margin-top: 20px;">
                    This is an electronic itinerary. No physical ticket is required.
                </p>
            </div>
        </body>
        </html>
        """
        
        return html
    
def get_pdf_generator(engine='auto'):
    """
    Factory function to get PDF generator based on engine preference
    
    Args:
        engine: 'reportlab', 'weasyprint', or 'auto' (default)
    
    Returns:
        PDFGenerator class
    """
    from django.conf import settings
    
    engine = engine or getattr(settings, 'PDF_GENERATOR', 'auto')
    
    if engine == 'reportlab':
        try:
            import reportlab
            return ReportLabPDFGenerator
        except ImportError:
            logger.warning("ReportLab not available, falling back to WeasyPrint")
            return WeasyPrintPDFGenerator
    
    elif engine == 'weasyprint':
        try:
            import weasyprint
            return WeasyPrintPDFGenerator
        except ImportError:
            logger.warning("WeasyPrint not available, falling back to ReportLab")
            return ReportLabPDFGenerator
    
    else:  # auto
        # Try ReportLab first, then WeasyPrint
        try:
            import reportlab
            return ReportLabPDFGenerator
        except ImportError:
            try:
                import weasyprint
                return WeasyPrintPDFGenerator
            except ImportError:
                raise ImportError("Neither ReportLab nor WeasyPrint are installed")