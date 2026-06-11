import json
from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import jwt_required
from werkzeug.exceptions import Conflict

from project import db
from project.api.roles.roles import roles_satisfied_module, roles_required
import project.api.roles.roles as roleSettings
from project.api.roles.models import Role
from project.api.auditlog.models import log_audit
from project.api.auth.utils import prevent_multiple_logins_per_user
from project.api.utils import validate_request

role = Blueprint('role', __name__)


@role.route('/permissions', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_role_permissions():
    """Query all roles"""
    roles, _, _, _ = roleSettings.load_roles_from_db()
    return make_response(jsonify(roles["roles"]), 200)


@role.route('/roles_variable', methods=['GET'])
@validate_request()
def get_roles_variable():
    """Query all roles"""
    return make_response(jsonify(roleSettings.load_roles_from_db()), 200)


@role.route('/all', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_all_roles():
    roles_required(*roleSettings.getRoles('uam', 'read'), action='Retrieve', module='uam', submodule='role')
    """Query all roles"""
    role_permission_list = [role_permission.to_dict() for role_permission in Role.query.all()]

    return make_response(jsonify(role_permission_list), 200)


@role.route('/name/<string:name>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_role_by_id(id):
    roles_required(*roleSettings.getRoles('uam', 'read'), action='Retrieve', module='uam', submodule='name')
    """Query role by uid"""
    try:
        role = Role.query.filter_by(id=id).first()
        if not role:
            raise Exception('Role not found')

        # audit log
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] retrieved user with id {id}',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify(role.to_dict()), 200)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to retrieve user with id {id}. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/add_batch', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['roles'])
def add_multi_roles():
    roles_required(*roleSettings.getRoles('uam', 'write'), action='Add', module='uam', submodule='role')
    """Add multiple roles"""
    try:
        data = request.get_json()
        roles = data.get('roles')
        if not roles:
            raise ValueError('No roles provided')

        for role_data in roles:
            name = role_data.get('name')
            module = role_data.get('module')
            permission_type = role_data.get('permission_type')

            role = Role.query.filter_by(name=name, module=module, permission_type=permission_type).first()
            if role:
                continue

            if not name:
                continue

            role = Role(name=name, module=module, permission_type=permission_type)
            db.session.add(role)
            db.session.commit()

        # audit log
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] added multiple roles',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify({'message': 'Roles added'}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Roles [$USER] failed to add multiple roles. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/add', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['name', 'module', 'permission_type'])
def add_user():
    roles_required(*roleSettings.getRoles('uam', 'write'), action='Add', module='uam', submodule='role')
    """Add role"""
    try:
        data = request.get_json()
        name = data.get('name')
        module = data.get('module')
        permission_type = data.get('permission_type')

        role = Role.query.filter_by(name=name, module=module, permission_type=permission_type).first()
        if role:
            raise Conflict('Role already exists')

        if not name:
            raise ValueError('Name is required')

        role = Role(name=name, module=module, permission_type=permission_type)
        db.session.add(role)
        db.session.commit()

        # audit log
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] added role {name}',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify(role.to_dict()), 201)

    except Conflict as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to add user {name}. Error: {str(e)}',
            error_codes='409',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 409)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Roles [$USER] failed to add user {name}. Error: {str(e)}',
            error_codes='400',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Add',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to add user {name}. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/update/<string:id>', methods=['PUT'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['id', 'name', 'module', 'permission_type'])
def update_role(id):
    roles_required(*roleSettings.getRoles('uam', 'write'), action='Update', module='uam', submodule='role')
    """Update role by id"""
    try:
        role = Role.query.filter_by(id=id).first()

        if not role:
            raise Exception('Role not found')

        data = request.get_json()
        name = data.get('name')
        module = data.get('module')
        permission_type = data.get('permission_type')

        previous_data = {}
        new_data = {}

        if name and name != role.name:
            previous_data['name'] = role.name
            new_data['name'] = name
            role.name = name

        if module and module != role.module:
            previous_data['module'] = role.module
            new_data['module'] = module
            role.module = module

        if permission_type and permission_type != role.permission_type:
            previous_data['permission_type'] = role.permission_type
            new_data['permission_type'] = permission_type
            role.permission_type = permission_type

        db.session.commit()

        # audit log
        log_audit(
            action='Update',
            module='uam',
            submodule='role',
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f'Role [$USER] updated role {name}',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify(role.to_dict()), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to update role {name}. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/updates', methods=['PUT'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['roles'])
def update_roles():
    """Update roles"""
    try:
        roles_satisfied_module('uam', 'write', action='Update', submodule='user')
        roles = request.get_json()['roles']
        for oneOfRoles in roles:
            id = oneOfRoles['id']

            role = Role.query.filter_by(id=id).first()
            if not role:
                raise Exception('Role not found')

            name = oneOfRoles['name'] if 'name' in oneOfRoles.keys() else None
            module = oneOfRoles['module'] if 'module' in oneOfRoles.keys() else None
            permission_type = oneOfRoles['permission_type'] if 'permission_type' in oneOfRoles.keys() else None

            previous_data = {}
            new_data = {}

            if name and name != role.name:
                previous_data['name'] = role.name
                new_data['name'] = name
                role.name = name

            if module and module != role.module:
                previous_data['module'] = role.module
                new_data['module'] = module
                role.module = module

            if permission_type and permission_type != role.permission_type:
                previous_data['permission_type'] = role.permission_type
                new_data['permission_type'] = permission_type
                role.permission_type = permission_type

            db.session.commit()

            # audit log
            log_audit(
                action='Update',
                module='uam',
                submodule='role',
                previous_data=json.dumps(previous_data),
                new_data=json.dumps(new_data),
                description=f'User [$USER] updated role {name}',
                error_codes='',
                database_involved='roles'
            )
        return make_response(jsonify({'message': 'Roles updated'}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to update roles. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/delete/<string:id>', methods=['DELETE'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def delete_role(id):
    roles_required(*roleSettings.getRoles('uam', 'write'), action='Delete', module='uam', submodule='role')
    """Delete role by id"""
    try:
        role = Role.query.filter_by(id=id).first()
        if not role:
            raise Exception('Role not found')
        db.session.delete(role)
        db.session.commit()

        # audit log
        log_audit(
            action='Delete',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] deleted role with id {id}',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify({'message': 'User deleted'}), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Delete',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to delete role with id {id}. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@role.route('/delete_batch', methods=['POST'])  # use POST instead of DELETE which httpClient does not support body parameter
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['roleIds'])
def delete_multi_roles():
    roles_required(*roleSettings.getRoles('uam', 'write'), action='Delete', module='uam', submodule='role')
    """Delete role by id"""
    try:
        data = request.get_json()
        roleIds = data.get('roleIds')
        for id in roleIds:
            role = Role.query.filter_by(id=id).first()
            if not role:
                raise Exception('Role not found')
            db.session.delete(role)
        db.session.commit()

        # audit log
        log_audit(
            action='Delete',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] deleted {len(roleIds)} roles',
            error_codes='',
            database_involved='roles'
        )
        return make_response(jsonify({'message': 'User deleted'}), 200)

    except Exception as e:
        log_audit(
            action='Delete',
            module='uam',
            submodule='role',
            previous_data='',
            new_data='',
            description=f'Role [$USER] failed to delete role with id {id}. Error: {str(e)}',
            error_codes='500',
            database_involved='roles'
        )
        return make_response(jsonify({'message': str(e)}), 500)
