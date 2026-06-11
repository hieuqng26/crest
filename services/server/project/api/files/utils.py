import os
import jwt
from datetime import datetime, timedelta


def create_download_token(jobId, module, submodule, is_staging, type, dbName, file_type,
                          download_file_name='download', expiry_minutes=30):
    """Create a temporary download token"""
    payload = {
        'jobId': jobId,
        'module': module,
        'submodule': submodule,
        'is_staging': is_staging,
        'type': type,
        'dbName': dbName,
        'download_file_name': download_file_name,
        'file_type': file_type,
        'exp': datetime.now() + timedelta(minutes=expiry_minutes)
    }

    secret_key = os.getenv('SECRET_KEY', 'your-secret-key')
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token


def verify_download_token(token):
    """Verify and decode download token"""
    try:
        secret_key = os.getenv('SECRET_KEY', 'your-secret-key')
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def parse_scenario_excel(file_stream) -> dict:
    """
    Parse scenario Excel file into dictionary format.

    Args:
        file_stream: File stream from request.files

    Returns:
        dict: Scenario configuration in expected format

    Raises:
        ValueError: If Excel is invalid or missing required columns
    """
    import pandas as pd

    try:
        # Read Excel file
        df = pd.read_excel(file_stream, sheet_name=0)  # Read first sheet
    except Exception as e:
        raise ValueError(f"Invalid Excel format: {str(e)}")

    # Validate required columns
    required_columns = ['scenario_id', 'item_type', 'shift_type']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    # Initialize config structure
    scenario_config = {
        'use_spreaded_term_structures': False,
        'scenarios': []
    }

    scenarios_dict = {}  # Track scenarios by ID

    # Process each row
    for _, row in df.iterrows():
        scenario_id = str(row['scenario_id']).strip()
        item_type = str(row['item_type']).strip()

        # Initialize scenario if not exists
        if scenario_id not in scenarios_dict:
            scenarios_dict[scenario_id] = {
                'id': scenario_id,
                'description': str(row.get('description', '')).strip() if pd.notna(row.get('description')) else '',
                'discount_curves': [],
                'fx_spots': [],
                'fx_volatilities': [],
                'swaption_volatilities': []
            }

        scenario = scenarios_dict[scenario_id]

        # Parse based on item type
        if item_type == 'DiscountCurve':
            ccy = str(row['ccy']).strip()
            shift_type = str(row['shift_type']).strip()

            # Parse shifts (comma-separated or single value)
            shifts_str = str(row['shifts']).strip()
            shifts = [float(s.strip()) for s in shifts_str.split(',')]

            # Parse tenors (comma-separated)
            tenors_str = str(row['shift_tenors']).strip()
            shift_tenors = [s.strip() for s in tenors_str.split(',')]

            scenario['discount_curves'].append({
                'ccy': ccy,
                'shift_type': shift_type,
                'shifts': shifts,
                'shift_tenors': shift_tenors
            })

        elif item_type == 'FXSpot':
            ccypair = str(row['ccypair']).strip()
            shift_type = str(row['shift_type']).strip()
            shift_size = float(row['shifts'])

            scenario['fx_spots'].append({
                'ccypair': ccypair,
                'shift_type': shift_type,
                'shift_size': shift_size
            })

        elif item_type == 'FXVolatility':
            ccypair = str(row['ccypair']).strip()
            shift_type = str(row['shift_type']).strip()

            # Parse shifts (comma-separated or single value)
            shifts_str = str(row['shifts']).strip()
            shifts = [float(s.strip()) for s in shifts_str.split(',')]

            # Parse expiries (comma-separated)
            expiries_str = str(row['shift_expiries']).strip()
            shift_expiries = [s.strip() for s in expiries_str.split(',')]

            scenario['fx_volatilities'].append({
                'ccypair': ccypair,
                'shift_type': shift_type,
                'shifts': shifts,
                'shift_expiries': shift_expiries
            })

        elif item_type == 'SwaptionVolatility':
            ccy = str(row['ccy']).strip()
            shift_type = str(row['shift_type']).strip()

            # Parse shifts (comma-separated floats)
            shifts_str = str(row['shifts']).strip()
            shifts = [float(s.strip()) for s in shifts_str.split(',')]

            # Parse expiries (comma-separated tenors, e.g. "1Y,5Y,10Y")
            expiries_str = str(row['shift_expiries']).strip()
            shift_expiries = [s.strip() for s in expiries_str.split(',')]

            # Parse terms (comma-separated swap terms, e.g. "1Y,5Y,10Y")
            terms_str = str(row['shift_terms']).strip()
            shift_terms = [s.strip() for s in terms_str.split(',')]

            scenario['swaption_volatilities'].append({
                'ccy': ccy,
                'shift_type': shift_type,
                'shifts': shifts,
                'shift_expiries': shift_expiries,
                'shift_terms': shift_terms
            })

        else:
            raise ValueError(f"Unknown item_type: {item_type}")

    # Convert scenarios dict to list
    scenario_config['scenarios'] = list(scenarios_dict.values())

    return scenario_config
