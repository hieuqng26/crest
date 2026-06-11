from datetime import datetime, timezone
import os
import json
from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import jwt_required
from werkzeug.exceptions import Conflict

from project import db, bcrypt
from project.api.users.models import User
from project.api.utils import valid_date, valid_uuid
from project.api.auditlog.models import log_audit
from project.api.auth.utils import prevent_multiple_logins_per_user
from project.api.utils import validate_request

user = Blueprint('user', __name__)


@user.route('/all', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_all_users():
    """Query all users"""
    users_list = [user.to_dict() for user in User.query.all()]
    return make_response(jsonify(users_list), 200)


@user.route('/is_local_system_admin/<string:username>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_is_local_system_admin(username):
    LOCAL_SYSTEM_ADMIN_USERNAME = os.getenv('LOCAL_SYSTEM_ADMIN_USERNAME')
    doMatch = username == LOCAL_SYSTEM_ADMIN_USERNAME
    return make_response(jsonify({'doMatch': doMatch}), 200)


@user.route('/id/<string:id>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_user_by_id(id):
    """Query user by uid"""
    try:
        id = valid_uuid(id)
        user = User.query.filter_by(id=id).first()
        if not user:
            raise Exception('User not found')

        # audit log
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved user with id {id}',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify(user.to_dict()), 200)

    except NameError as e:
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve user with id {id}. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/email/<string:email>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_user_by_email(email):
    """Query user by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            raise Exception('User not found')

        # audit log
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved user with email {email}',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify(user.to_dict()), 200)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve user with email {email}. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/add_batch', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['users'])
def add_multi_users():
    """Add multiple users"""
    try:
        data = request.get_json()
        users = data.get('users')
        if not users:
            raise ValueError('No users provided')

        for user_data in users:
            email = user_data.get('email')
            password = user_data.get('password')
            role = user_data.get('role')
            name = user_data.get('name')
            status = user_data.get('status')
            registered_on = user_data.get('registeredOn', datetime.now(timezone.utc))

            user = User.query.filter_by(email=email).first()
            if user:
                continue

            if not email or not password or not role:
                continue

            user = User(email=email, password=password, role=role, name=name, status=status, registered_on=valid_date(registered_on))
            db.session.add(user)
            db.session.commit()

        # audit log
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] added multiple users',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify({'message': 'Users added'}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add multiple users. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/add', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'password', 'role', 'name', 'status', 'registeredOn'])
def add_user():
    """Add user"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        role = data.get('role')
        name = data.get('name')
        status = data.get('status')
        registered_on = data.get('registeredOn')

        user = User.query.filter_by(email=email).first()
        if user:
            raise Conflict('User already exists')

        if not email or not password or not role:
            raise ValueError('Email, password, and role are required')

        user = User(email=email, password=password, role=role, name=name, status=status, registered_on=valid_date(registered_on))
        db.session.add(user)
        db.session.commit()

        # audit log
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] added user {email}',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify(user.to_dict()), 201)

    except Conflict as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add user {email}. Error: {str(e)}',
            error_codes='409',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 409)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add user {email}. Error: {str(e)}',
            error_codes='400',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add user {email}. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/update/<string:email>', methods=['PUT'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'password', 'role', 'name', 'status', 'registeredOn'])
def update_user(email):
    """Update user by email"""
    try:
        user = User.query.filter_by(email=email).first()

        if not user:
            raise Exception('User not found')

        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        role = data.get('role')
        name = data.get('name')
        status = data.get('status')
        registered_on = data.get('registeredOn')

        previous_data = {}
        new_data = {}

        if email and email != user.email:
            previous_data['email'] = user.email
            new_data['email'] = email
            user.email = email

        if password and password != user.password:
            password = bcrypt.generate_password_hash(password).decode('utf-8')
            user.password = password

        if role and role != user.role:
            previous_data['role'] = user.role
            new_data['role'] = role
            user.role = role

        if name and name != user.name:
            previous_data['name'] = user.name
            new_data['name'] = name
            user.name = name

        if status and status != user.status:
            previous_data['status'] = user.status
            new_data['status'] = status
            user.status = status

        if registered_on:
            registered_on = valid_date(registered_on, dayfirst=False)
            if registered_on != user.registered_on:
                previous_data['registered_on'] = user.registered_on.strftime('%Y-%m-%d')
                new_data['registered_on'] = registered_on.strftime('%Y-%m-%d')
                user.registered_on = registered_on

        db.session.commit()

        # audit log
        log_audit(
            action='Update',
            module='uam',
            submodule='user',
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f'User [$USER] updated user {email}',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify(user.to_dict()), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to update user {email}. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/updates', methods=['PUT'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['users'])
def update_users():
    """Update users"""
    try:
        users = request.get_json()['users']
        for oneOfUsers in users:
            email = oneOfUsers['email']

            user = User.query.filter_by(email=email).first()
            if not user:
                raise Exception('User not found')

            password = oneOfUsers['password'] if 'password' in oneOfUsers.keys() else None
            role = oneOfUsers['role'] if 'role' in oneOfUsers.keys() else None
            name = oneOfUsers['name'] if 'name' in oneOfUsers.keys() else None
            status = oneOfUsers['status'] if 'status' in oneOfUsers.keys() else None
            registered_on = oneOfUsers['registeredOn'] if 'registeredOn' in oneOfUsers.keys() else None

            previous_data = {}
            new_data = {}

            if email and email != user.email:
                previous_data['email'] = user.email
                new_data['email'] = email
                user.email = email

            if password and password != user.password:
                password = bcrypt.generate_password_hash(password).decode('utf-8')
                user.password = password

            if role and role != user.role:
                previous_data['role'] = user.role
                new_data['role'] = role
                user.role = role

            if name and name != user.name:
                previous_data['name'] = user.name
                new_data['name'] = name
                user.name = name

            if status and status != user.status:
                previous_data['status'] = user.status
                new_data['status'] = status
                user.status = status

            if registered_on:
                registered_on = valid_date(registered_on, dayfirst=False)
                if registered_on != user.registered_on:
                    previous_data['registered_on'] = user.registered_on.strftime('%Y-%m-%d')
                    new_data['registered_on'] = registered_on.strftime('%Y-%m-%d')
                    user.registered_on = registered_on

            db.session.commit()

            # audit log
            log_audit(
                action='Update',
                module='uam',
                submodule='user',
                previous_data=json.dumps(previous_data),
                new_data=json.dumps(new_data),
                description=f'User [$USER] updated user {email}',
                error_codes='',
                database_involved='users'
            )
        return make_response(jsonify({'message': 'Users updated'}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to update users. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@user.route('/delete/<string:email>', methods=['DELETE'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def delete_user(email):
    """Delete user by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            raise Exception('User not found')
        db.session.delete(user)
        db.session.commit()

        # audit log
        log_audit(
            action='Delete',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] deleted user {email}',
            error_codes='',
            database_involved='users'
        )
        return make_response(jsonify({'message': 'User deleted'}), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Delete',
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to delete user {email}. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        return make_response(jsonify({'message': str(e)}), 500)
