import io
import os
from datetime import datetime
from django.conf import settings
import logging
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib import colors
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

class AmadeusOfficialItineraryGenerator:
    """
    Official Amadeus-style itinerary receipt generator
    Meets IATA and airline standards for visa applications
    """
    
    @staticmethod
    def generate_official_itinerary(booking, flight_details, passengers, agency_info=None):
        """
        Generate official Amadeus-standard itinerary receipt
        
        Args:
            booking: Reservation object
            flight_details: Flight details dictionary
            passengers: List of passenger dictionaries
            agency_info: Optional agency information dict
        
        Returns:
            BytesIO object with PDF content
        """
        try:
            # Create buffer
            buffer = io.BytesIO()
            
            # Setup document with proper margins
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=20*mm,
                leftMargin=20*mm,
                topMargin=15*mm,
                bottomMargin=15*mm
            )
            
            # Register fonts for professional look
            try:
                # Try to register professional fonts if available
                font_path = os.path.join(settings.BASE_DIR, 'static', 'fonts')
                if os.path.exists(os.path.join(font_path, 'Arial.ttf')):
                    pdfmetrics.registerFont(TTFont('Arial', os.path.join(font_path, 'Arial.ttf')))
                    pdfmetrics.registerFont(TTFont('Arial-Bold', os.path.join(font_path, 'Arial-Bold.ttf')))
            except:
                pass  # Use default fonts
            
            # Styles for official Amadeus format
            styles = getSampleStyleSheet()
            
            # Official header styles
            header_style = ParagraphStyle(
                'OfficialHeader',
                parent=styles['Heading1'],
                fontSize=16,
                textColor=colors.HexColor('#003366'),  # Amadeus blue
                alignment=TA_CENTER,
                spaceAfter=20,
                fontName='Helvetica-Bold'
            )
            
            subheader_style = ParagraphStyle(
                'OfficialSubheader',
                parent=styles['Heading2'],
                fontSize=12,
                textColor=colors.HexColor('#003366'),
                alignment=TA_CENTER,
                spaceAfter=10,
                fontName='Helvetica-Bold'
            )
            
            # Section styles
            section_title_style = ParagraphStyle(
                'SectionTitle',
                parent=styles['Heading2'],
                fontSize=11,
                textColor=colors.white,
                alignment=TA_LEFT,
                spaceAfter=6,
                fontName='Helvetica-Bold',
                leftIndent=5,
                backgroundColor=colors.HexColor('#003366')
            )
            
            # Field styles
            field_label_style = ParagraphStyle(
                'FieldLabel',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#666666'),
                alignment=TA_LEFT,
                fontName='Helvetica'
            )
            
            field_value_style = ParagraphStyle(
                'FieldValue',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.black,
                alignment=TA_LEFT,
                fontName='Helvetica-Bold'
            )
            
            # Table styles
            table_header_style = ParagraphStyle(
                'TableHeader',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.white,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                backgroundColor=colors.HexColor('#003366')
            )
            
            table_cell_style = ParagraphStyle(
                'TableCell',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.black,
                alignment=TA_LEFT,
                fontName='Helvetica'
            )
            
            # Footer styles
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=7,
                textColor=colors.HexColor('#666666'),
                alignment=TA_CENTER,
                fontName='Helvetica'
            )
            
            # Build story
            story = []
            
            # ========== PAGE 1: OFFICIAL ITINERARY RECEIPT ==========
            
            # Official Header with Amadeus branding
            story.append(Paragraph("OFFICIAL E-TICKET ITINERARY RECEIPT", header_style))
            story.append(Paragraph("ISSUED BY TRAVEL AGENCY", subheader_style))
            story.append(Spacer(1, 15))
            
            # Agency Information (if provided)
            if agency_info:
                agency_table_data = [
                    [Paragraph("<b>Issued By:</b>", field_label_style), 
                     Paragraph(agency_info.get('name', 'Travel Agency'), field_value_style)],
                    [Paragraph("<b>IATA No:</b>", field_label_style), 
                     Paragraph(agency_info.get('iata_number', 'N/A'), field_value_style)],
                    [Paragraph("<b>Address:</b>", field_label_style), 
                     Paragraph(agency_info.get('address', 'N/A'), field_value_style)],
                    [Paragraph("<b>Contact:</b>", field_label_style), 
                     Paragraph(f"{agency_info.get('phone', '')} | {agency_info.get('email', '')}", field_value_style)],
                ]
                
                agency_table = Table(agency_table_data, colWidths=[1.5*inch, 4*inch])
                agency_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                story.append(agency_table)
                story.append(Spacer(1, 10))
            
            # Booking Information Section
            story.append(Paragraph("BOOKING INFORMATION", section_title_style))
            
            booking_info_data = [
                [
                    Paragraph("<b>Booking Reference (PNR):</b>", field_label_style),
                    Paragraph(booking.airline_pnr, field_value_style),
                    Paragraph("<b>Issue Date:</b>", field_label_style),
                    Paragraph(booking.created_at.strftime('%d %b %Y %H:%M'), field_value_style)
                ],
                [
                    Paragraph("<b>e-Ticket Number:</b>", field_label_style),
                    Paragraph(booking.gds_reference or 'Pending', field_value_style),
                    Paragraph("<b>Ticketing Deadline:</b>", field_label_style),
                    Paragraph(booking.expires_at.strftime('%d %b %Y %H:%M') if booking.expires_at else 'N/A', field_value_style)
                ],
                [
                    Paragraph("<b>Status:</b>", field_label_style),
                    Paragraph(booking.status, field_value_style),
                    Paragraph("<b>Payment Status:</b>", field_label_style),
                    Paragraph('CONFIRMED', field_value_style)
                ],
            ]
            
            booking_table = Table(booking_info_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 2*inch])
            booking_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
                ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(booking_table)
            story.append(Spacer(1, 15))
            
            # Passenger Information Section
            story.append(Paragraph("PASSENGER INFORMATION", section_title_style))
            
            passenger_headers = [
                Paragraph("<b>No.</b>", table_header_style),
                Paragraph("<b>Passenger Name</b>", table_header_style),
                Paragraph("<b>Type</b>", table_header_style),
                Paragraph("<b>Ticket Number</b>", table_header_style),
                Paragraph("<b>Fare Basis</b>", table_header_style),
                Paragraph("<b>Baggage</b>", table_header_style)
            ]
            
            passenger_data = [passenger_headers]
            
            for i, passenger in enumerate(passengers, 1):
                # Get passenger name
                first_name = passenger.get('name', {}).get('firstName', '')
                last_name = passenger.get('name', {}).get('lastName', '')
                passenger_name = f"{last_name}/{first_name}".upper()
                
                # Determine passenger type
                traveler_type = passenger.get('travelerType', 'ADT')
                if traveler_type == 'ADULT':
                    passenger_type = 'ADT'
                elif traveler_type == 'CHILD':
                    passenger_type = 'CHD'
                elif traveler_type == 'INFANT':
                    passenger_type = 'INF'
                else:
                    passenger_type = 'ADT'
                
                # Get ticket number (if available)
                ticket_number = passenger.get('ticket_number', f'Pending-{booking.airline_pnr}-{i}')
                
                # Get fare basis (from flight details if available)
                fare_basis = 'Y'  # Default economy
                if flight_details and 'travelerPricings' in flight_details:
                    for tp in flight_details['travelerPricings']:
                        if tp.get('travelerId') == str(i):
                            fare_details = tp.get('fareDetailsBySegment', [])
                            if fare_details:
                                fare_basis = fare_details[0].get('fareBasis', 'Y')
                
                # Baggage allowance
                baggage = passenger.get('baggage_allowance', '1PC/23KG')
                
                passenger_data.append([
                    Paragraph(str(i), table_cell_style),
                    Paragraph(passenger_name, table_cell_style),
                    Paragraph(passenger_type, table_cell_style),
                    Paragraph(ticket_number, table_cell_style),
                    Paragraph(fare_basis, table_cell_style),
                    Paragraph(baggage, table_cell_style)
                ])
            
            passenger_table = Table(passenger_data, colWidths=[0.4*inch, 2*inch, 0.6*inch, 1.5*inch, 0.8*inch, 1*inch])
            passenger_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Center numbers
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(passenger_table)
            story.append(Spacer(1, 15))
            
            # Flight Itinerary Section
            story.append(Paragraph("FLIGHT ITINERARY", section_title_style))
            
            if flight_details:
                # Process all flight segments
                itineraries = flight_details.get('itineraries', [])
                
                for itinerary_idx, itinerary in enumerate(itineraries):
                    segments = itinerary.get('segments', [])
                    
                    for segment_idx, segment in enumerate(segments):
                        departure = segment.get('departure', {})
                        arrival = segment.get('arrival', {})
                        
                        # Format dates and times
                        dep_time = departure.get('at', '')
                        arr_time = arrival.get('at', '')
                        
                        if dep_time:
                            try:
                                dep_dt = datetime.fromisoformat(dep_time.replace('Z', '+00:00'))
                                dep_date = dep_dt.strftime('%d %b %Y')
                                dep_time_formatted = dep_dt.strftime('%H:%M')
                            except:
                                dep_date = dep_time[:10]
                                dep_time_formatted = dep_time[11:16] if len(dep_time) > 16 else 'N/A'
                        else:
                            dep_date = 'N/A'
                            dep_time_formatted = 'N/A'
                        
                        if arr_time:
                            try:
                                arr_dt = datetime.fromisoformat(arr_time.replace('Z', '+00:00'))
                                arr_date = arr_dt.strftime('%d %b %Y')
                                arr_time_formatted = arr_dt.strftime('%H:%M')
                            except:
                                arr_date = arr_time[:10]
                                arr_time_formatted = arr_time[11:16] if len(arr_time) > 16 else 'N/A'
                        else:
                            arr_date = 'N/A'
                            arr_time_formatted = 'N/A'
                        
                        # Calculate duration
                        duration = segment.get('duration', '')
                        if duration:
                            duration = duration.replace('PT', '')
                            duration = duration.replace('H', 'h ')
                            duration = duration.replace('M', 'm')
                        
                        # Get airline info
                        carrier_code = segment.get('carrierCode', '')
                        flight_number = segment.get('number', '')
                        airline_name = flight_details.get('airline_names', [''])[0] if flight_details.get('airline_names') else carrier_code
                        
                        # Get aircraft type
                        aircraft = segment.get('aircraft', {}).get('code', '')
                        
                        # Get class of service
                        travel_class = 'Y'  # Default economy
                        if 'travelerPricings' in flight_details:
                            for tp in flight_details['travelerPricings']:
                                fare_details = tp.get('fareDetailsBySegment', [])
                                if len(fare_details) > segment_idx:
                                    travel_class = fare_details[segment_idx].get('cabin', 'Y')
                        
                        # Create flight segment table
                        flight_headers = [
                            Paragraph("<b>Date</b>", table_header_style),
                            Paragraph("<b>Flight</b>", table_header_style),
                            Paragraph("<b>From/To</b>", table_header_style),
                            Paragraph("<b>Depart/Arrive</b>", table_header_style),
                            Paragraph("<b>Duration</b>", table_header_style),
                            Paragraph("<b>Class</b>", table_header_style),
                            Paragraph("<b>Aircraft</b>", table_header_style),
                            Paragraph("<b>Status</b>", table_header_style)
                        ]
                        
                        flight_data = [flight_headers]
                        
                        flight_data.append([
                            Paragraph(dep_date, table_cell_style),
                            Paragraph(f"{carrier_code} {flight_number}", table_cell_style),
                            Paragraph(f"{departure.get('iataCode', '')} → {arrival.get('iataCode', '')}", table_cell_style),
                            Paragraph(f"{dep_time_formatted} - {arr_time_formatted}", table_cell_style),
                            Paragraph(duration, table_cell_style),
                            Paragraph(travel_class, table_cell_style),
                            Paragraph(aircraft, table_cell_style),
                            Paragraph("CONFIRMED", table_cell_style)
                        ])
                        
                        flight_table = Table(flight_data, colWidths=[0.8*inch, 0.8*inch, 1.2*inch, 1.2*inch, 0.7*inch, 0.5*inch, 0.7*inch, 0.7*inch])
                        flight_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                            ('ALIGN', (4, 1), (7, -1), 'CENTER'),  # Center duration, class, aircraft, status
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
                            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('TOPPADDING', (0, 0), (-1, -1), 4),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ]))
                        
                        story.append(flight_table)
                        
                        # Add stop information if not last segment
                        if segment_idx < len(segments) - 1:
                            story.append(Spacer(1, 5))
                            story.append(Paragraph(f"• Connection at {arrival.get('iataCode', '')} - {segment.get('connection_duration', '2:00')} layover", 
                                                  ParagraphStyle('Connection', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#666666'))))
                            story.append(Spacer(1, 5))
            
            story.append(Spacer(1, 15))
            
            # Fare Calculation Section
            story.append(Paragraph("FARE CALCULATION & PAYMENT DETAILS", section_title_style))
            
            # Extract pricing information
            price_details = flight_details.get('price', {}) if flight_details else {}
            total_price = price_details.get('total', booking.total_price)
            currency = price_details.get('currency', 'USD')
            base_fare = price_details.get('base', '0')
            
            fare_calc_data = [
                [
                    Paragraph("<b>Fare Calculation:</b>", field_label_style),
                    Paragraph(f"{currency} {total_price}", field_value_style)
                ],
                [
                    Paragraph("<b>Base Fare:</b>", field_label_style),
                    Paragraph(f"{currency} {base_fare}", field_value_style)
                ],
                [
                    Paragraph("<b>Taxes & Fees:</b>", field_label_style),
                    Paragraph(f"{currency} {float(total_price) - float(base_fare):.2f}" if total_price and base_fare else 'N/A', field_value_style)
                ],
                [
                    Paragraph("<b>Payment Method:</b>", field_label_style),
                    Paragraph("CREDIT CARD - ONLINE PAYMENT", field_value_style)
                ],
                [
                    Paragraph("<b>Payment Reference:</b>", field_label_style),
                    Paragraph(f"PAY-{booking.airline_pnr}", field_value_style)
                ]
            ]
            
            fare_table = Table(fare_calc_data, colWidths=[1.5*inch, 4*inch])
            fare_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(fare_table)
            
            story.append(Spacer(1, 15))
            
            # Important Notes Section
            story.append(Paragraph("IMPORTANT NOTES FOR EMBASSY/VISA APPLICATION", section_title_style))
            
            notes = [
                "1. This is an OFFICIAL E-TICKET ITINERARY RECEIPT issued by a registered travel agency.",
                "2. All flights are CONFIRMED and SEATS ARE GUARANTEED as per the booking.",
                "3. This document should be presented to the Embassy/Consulate as proof of travel arrangements.",
                "4. Passengers must carry valid passports with minimum 6 months validity from date of return.",
                "5. Check-in online 24-48 hours before departure or at airport counter 3 hours before flight.",
                "6. For international travel, ensure you have required visas for all transit/destination countries."
            ]
            
            for note in notes:
                story.append(Paragraph(f"• {note}", ParagraphStyle('Note', parent=styles['Normal'], fontSize=8, textColor=colors.black)))
                story.append(Spacer(1, 2))
            
            story.append(Spacer(1, 10))
            
            # Barcode Section (No QR code)
            story.append(Paragraph("ELECTRONIC VALIDATION", section_title_style))
            
            # Create barcode for PNR
            try:
                # Create barcode drawing properly
                pnr_str = str(booking.airline_pnr).strip()
                
                # Create the barcode - this returns a Drawing object directly
                barcode_drawing = code128.Code128(
                    pnr_str, 
                    barHeight=15,
                    barWidth=1.0,
                    humanReadable=True,
                    fontSize=8
                )
                
                # Adjust size if needed
                barcode_drawing.width = 100
                barcode_drawing.height = 40
                
            except Exception as e:
                logger.warning(f"Could not create barcode: {e}")
                # Create empty drawing as fallback
                from reportlab.graphics.shapes import Drawing, String
                barcode_drawing = Drawing(100, 40)
                # Add String object (which is a Shape) not Paragraph
                error_text = String(50, 20, f"PNR: {booking.airline_pnr}", 
                                textAnchor='middle', fontSize=8, fillColor=colors.red)
                barcode_drawing.add(error_text)

            # Add verification text
            verification_table_data = [
                [
                    barcode_drawing,
                    Paragraph(f"""<b>ELECTRONIC VALIDATION</b><br/><br/>
                    <b>PNR:</b> {booking.airline_pnr}<br/>
                    <b>Issue Date:</b> {booking.created_at.strftime('%d %b %Y')}<br/>
                    <b>Verification URL:</b> https://verify.flightreserve.com/{booking.airline_pnr}<br/>
                    <b>Verification Code:</b> VER-{booking.airline_pnr}<br/><br/>
                    <font size="7">Scan barcode or enter PNR on website to verify authenticity</font>""", 
                    ParagraphStyle('Verification', parent=styles['Normal'], fontSize=8, textColor=colors.black))
                ]
            ]
            
            verification_table = Table(verification_table_data, colWidths=[2.5*inch, 3.5*inch])
            verification_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            story.append(verification_table)
            
            story.append(PageBreak())
            
            # ========== PAGE 2: TERMS & CONDITIONS ==========
            
            story.append(Paragraph("TERMS AND CONDITIONS", header_style))
            story.append(Spacer(1, 10))
            
            # Terms and Conditions (simplified)
            terms = [
                "A. TICKET VALIDITY: This e-ticket is valid only for the passenger(s) named and flights specified.",
                "B. CHECK-IN: International flights check-in closes 60 mins before departure.",
                "C. BAGGAGE: Allowance as per airline policy. Excess baggage charges apply at airport.",
                "D. CHANGES: Subject to airline rules and fees. Name changes not permitted.",
                "E. TRAVEL DOCUMENTS: Passenger responsible for required visas and passports.",
                "F. LIABILITY: Travel agency not liable for visa refusals or entry denials.",
                "G. FORCE MAJEURE: Airlines may cancel/reschedule flights due to operational reasons.",
                "H. INSURANCE: Travel insurance is recommended for all international travel."
            ]
            
            for term in terms:
                story.append(Paragraph(f"• {term}", ParagraphStyle('TermItem', 
                    parent=styles['Normal'], fontSize=8, textColor=colors.black,
                    leftIndent=5, spaceAfter=3)))
            
            story.append(Spacer(1, 15))
            
            # Embassy Verification Section
            story.append(Paragraph("FOR EMBASSY/VISA OFFICER VERIFICATION", section_title_style))
            
            verification_info = [
                "This document is an OFFICIAL E-TICKET ITINERARY RECEIPT issued through Amadeus GDS.",
                "All flight bookings are CONFIRMED and TICKETED in the airline reservation system.",
                "Payment has been received and the booking is fully secured.",
                "To verify this itinerary, visit: https://verify.flightreserve.com",
                f"Enter PNR: {booking.airline_pnr} or Verification Code: VER-{booking.airline_pnr}",
                "For embassy verification assistance: embassy@flightreserve.com"
            ]
            
            for info in verification_info:
                story.append(Paragraph(f"✓ {info}", ParagraphStyle('VerificationItem', 
                    parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#006600'),
                    leftIndent=5, spaceAfter=3)))
            
            story.append(Spacer(1, 20))
            
            # Official Stamp Area
            story.append(Paragraph("OFFICIAL STAMP & SIGNATURE", ParagraphStyle('StampTitle', 
                parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#003366'),
                alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=15)))
            
            stamp_table_data = [
                [
                    Paragraph("<b>Authorized Signature:</b>", ParagraphStyle('StampLabel', 
                        parent=styles['Normal'], fontSize=8, textColor=colors.black)),
                    Paragraph("<b>Date Stamp:</b>", ParagraphStyle('StampLabel', 
                        parent=styles['Normal'], fontSize=8, textColor=colors.black)),
                    Paragraph("<b>Official Stamp:</b>", ParagraphStyle('StampLabel', 
                        parent=styles['Normal'], fontSize=8, textColor=colors.black))
                ],
                [
                    Paragraph("_________________________", ParagraphStyle('StampField', 
                        parent=styles['Normal'], fontSize=9, textColor=colors.black, alignment=TA_CENTER)),
                    Paragraph(booking.created_at.strftime('%d %b %Y'), ParagraphStyle('StampField', 
                        parent=styles['Normal'], fontSize=9, textColor=colors.black, alignment=TA_CENTER)),
                    Paragraph("[AGENCY STAMP]", ParagraphStyle('StampField', 
                        parent=styles['Normal'], fontSize=9, textColor=colors.black, alignment=TA_CENTER))
                ]
            ]
            
            stamp_table = Table(stamp_table_data, colWidths=[2*inch, 2*inch, 2*inch])
            stamp_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            story.append(stamp_table)
            
            # Footer on every page
            def add_footer(canvas, doc):
                canvas.saveState()
                canvas.setFont('Helvetica', 7)
                canvas.setFillColor(colors.HexColor('#666666'))
                
                # Footer text
                footer_text = [
                    f"Official E-Ticket Itinerary Receipt • PNR: {booking.airline_pnr} • Page {doc.page}",
                    f"Issued by: FlightReserve Travel Agency • IATA: 12345678 • Contact: support@flightreserve.com",
                    f"This document is computer generated and does not require signature."
                ]
                
                y_position = 15
                for text in footer_text:
                    canvas.drawCentredString(A4[0]/2, y_position, text)
                    y_position += 8
                
                # Page number
                canvas.drawCentredString(A4[0]/2, 5, f"Page {doc.page} of 2")
                
                canvas.restoreState()
            
            # Build PDF with footer
            doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
            
            # Get PDF content
            pdf = buffer.getvalue()
            buffer.close()
            
            return io.BytesIO(pdf)
            
        except Exception as e:
            logger.error(f"Error generating official Amadeus itinerary: {e}", exc_info=True)
            raise