from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse
from app.core.security import get_current_user
from app.models.user import User
import re

from app.schemas.user import AuthContext

router = APIRouter()


def generate_slug(name: str) -> str:
    """Generate a URL-safe slug from a name"""
    # Convert to lowercase
    slug = name.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Remove any characters that aren't alphanumeric or hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Strip leading/trailing hyphens
    slug = slug.strip('-')
    return slug


@router.post("", response_model=CategoryResponse)
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user),
):
    """Create a new category for an organization"""
    # Generate slug from name
    slug = generate_slug(category.name)
    
    # Check if slug already exists for this organization
    existing = db.query(Category).filter(
        Category.slug == slug,
        Category.org_id == current_user.org_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category with this name already exists for this organization"
        )
    
    db_category = Category(
        name=category.name,
        slug=slug,
        org_id=current_user.org_id
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


@router.get("", response_model=List[CategoryResponse])
def list_categories(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user)
):
    """List all categories for an organization"""
    categories = db.query(Category).filter(Category.org_id == current_user.org_id).all()
    return categories


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user)
):
    """Get a specific category by ID"""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    return category


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user)
):
    """Update a category"""
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Update slug if name changed
    new_slug = generate_slug(category_update.name)
    
    # Check if new slug already exists
    existing = db.query(Category).filter(
        Category.slug == new_slug,
        Category.org_id == current_user.org_id,
        Category.id != category_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category with this name already exists for this organization"
        )
    
    db_category.name = category_update.name
    db_category.slug = new_slug
    
    db.commit()
    db.refresh(db_category)
    return db_category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user)
):
    """Delete a category"""
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    db.delete(db_category)
    db.commit() 
    return None
    

